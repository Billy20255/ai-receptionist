"""
The telephony front door. Twilio hits these two endpoints:
  POST /voice          — call just connected, greet + gather first speech
  POST /voice/gather    — every subsequent turn, after Twilio's <Gather>
                          transcribes what the caller said

This is a <Gather>-based loop (Twilio transcribes each utterance and POSTs
the text back to us), not full Media Streams. That's the pragmatic MVP per
the spec's Phase 1 scope — good enough to validate the flow end-to-end.
Swapping to Media Streams for lower latency / interruption handling is real
follow-on work, flagged in the README, not done here.
"""
from __future__ import annotations

from fastapi import FastAPI, Form
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather

from app.config import settings
from app.models import CallState, LeadStatus
from app.services.calendar_service import book_slot, find_next_available_slot
from app.services.conversation import run_turn, score_lead
from app.services.dispatch import send_dispatch_notification

app = FastAPI(title="AI Receptionist / Dispatch")

# In-memory call state, keyed by Twilio CallSid.
# Fine for a single-instance pilot. Move to Redis before multi-tenant scale
# (per the implementation spec's own sequencing note — don't build this
# early, it's wasted effort before you have the call volume to need it).
_CALLS: dict[str, CallState] = {}

MAX_TURNS_BEFORE_TIMEOUT = 12  # safety valve against a runaway/looping call


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/voice")
async def voice_entry(CallSid: str = Form(...), From: str = Form(...)):
    """First hit when a call connects. No address yet — just greet and listen."""
    state = CallState(call_sid=CallSid, from_number=From)
    _CALLS[CallSid] = state

    vr = VoiceResponse()
    gather = Gather(
        input="speech",
        action="/voice/gather",
        method="POST",
        speech_timeout="auto",
    )
    gather.say(
        "Thanks for calling. I can help get you a quote or set up an "
        "appointment. To start, what's the address of the property?"
    )
    vr.append(gather)
    # If they say nothing, Twilio falls through here — give one retry.
    vr.redirect("/voice")
    return Response(content=str(vr), media_type="application/xml")


@app.post("/voice/gather")
async def voice_gather(
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=""),
):
    """Every subsequent turn. Runs the caller's speech through the Claude
    agent, speaks the reply, and either keeps gathering or wraps up the call
    once qualifying is complete."""
    state = _CALLS.get(CallSid)
    vr = VoiceResponse()

    if state is None:
        # Shouldn't happen, but don't crash the call — restart gracefully.
        vr.redirect("/voice")
        return Response(content=str(vr), media_type="application/xml")

    if not SpeechResult:
        gather = Gather(input="speech", action="/voice/gather", method="POST", speech_timeout="auto")
        gather.say("Sorry, I didn't catch that. Could you say that again?")
        vr.append(gather)
        return Response(content=str(vr), media_type="application/xml")

    if state.turn_count >= MAX_TURNS_BEFORE_TIMEOUT:
        vr.say("Thanks for the info — someone from our team will follow up with you shortly.")
        vr.hangup()
        _finalize_call(state)
        return Response(content=str(vr), media_type="application/xml")

    reply_text = await run_turn(state, SpeechResult)

    # Qualifying is done once we've logged 6 caller turns (matches the 6
    # questions in the project notes / SYSTEM_PROMPT).
    if len(state.qa_history) >= 6:
        _finalize_call(state)

        vr.say(reply_text)
        if state.lead_status == LeadStatus.HOT:
            slot = find_next_available_slot()
            if slot:
                event_id = book_slot(
                    slot,
                    summary=f"Home consult — {state.from_number}",
                    description=f"Address: {state.address_raw}",
                )
                state.booked_slot = slot.strftime("%A %B %d at %I:%M %p")
                vr.say(f"I've got you booked for {state.booked_slot}. We'll see you then.")
            else:
                vr.say("I'll have someone call you back shortly to lock in a time.")
            send_dispatch_notification(state)
        else:
            vr.say("Thanks — I'll pass this along and someone will follow up if it's a fit.")
        vr.hangup()
        return Response(content=str(vr), media_type="application/xml")

    gather = Gather(input="speech", action="/voice/gather", method="POST", speech_timeout="auto")
    gather.say(reply_text)
    vr.append(gather)
    return Response(content=str(vr), media_type="application/xml")


def _finalize_call(state: CallState) -> None:
    score_lead(state)
    # TODO: write state to the CRM of record here (Sheets for the pilot,
    # GHL sub-account once Phase 3 of the implementation spec kicks in).
    # Deliberately not implemented yet — pick ONE destination before
    # go-live rather than building both.
