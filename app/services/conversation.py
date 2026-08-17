"""
The actual "brain" of the call. Claude drives the conversation turn by turn:
  - first turn: ask for the address (required trigger, per project notes —
    nothing gets looked up before this)
  - once address is given: call the property_lookup tool, then personalize
    the qualifying questions using what came back
  - after qualifying questions: apply the pass/fail gate and produce a score

This mirrors Speed-to-Lead's scoring approach (base + signals) rather than
a fully open-ended AI judgment call, so the same person tuning one can tune
both with the same mental model.
"""
from __future__ import annotations

import json

from anthropic import Anthropic

from app.config import settings
from app.models import CallState, LeadStatus
from app.services.property_lookup import lookup_property

_client: Anthropic | None = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


SYSTEM_PROMPT = """You are the phone receptionist for a South Florida home-services \
business (impact windows / roofing). You're speaking with a homeowner who just called \
in, likely because of a real problem (leak, storm damage) or a quote request.

Your job, strictly in this order:
1. If you don't yet have their address, ask for it. Nothing else happens before this.
2. Once you have an address, call the lookup_property tool with it.
3. Ask the following qualifying questions ONE AT A TIME, conversationally, not as a list:
   - What's happening: leak, visible damage, or just a quote/inspection request?
   - How old is the roof / when were windows last replaced?
   - Are they the homeowner or a renter? (cross-check against property owner name if available)
   - Is an insurance claim involved?
   - Timeline: emergency, or just gathering quotes?
   - Are they the decision-maker for this purchase?
4. Keep responses SHORT — this is a phone call, not a chat window. One sentence \
   or question per turn, plain conversational language, no corporate tone, no emojis.
5. If they say they're a renter, close politely — this business only works with \
   homeowners on impact projects.
6. Once all questions are answered, tell them you'll get them booked and hand off \
   to scheduling.

Never make up property data. If the lookup tool reports it couldn't find the \
property, just ask the caller directly for anything you need (e.g. approximate \
square footage) instead of guessing.
"""

TOOLS = [
    {
        "name": "lookup_property",
        "description": (
            "Look up public property record data (owner name, year built, "
            "square footage) for an address the caller just gave, using the "
            "county's open GIS parcel data. Call this exactly once, right "
            "after the caller states their address."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "The address as the caller stated it.",
                }
            },
            "required": ["address"],
        },
    }
]


async def run_turn(state: CallState, caller_speech: str) -> str:
    """One turn of the call: feed in what the caller just said, get back
    what the receptionist should say next. Mutates `state` in place
    (qa_history, property, turn_count) and returns the reply text."""

    state.turn_count += 1
    messages = _build_message_history(state, caller_speech)

    client = get_client()
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=messages,
    )

    # Handle a tool call (property lookup) inline, then ask Claude to
    # continue with the tool result before returning speech to the caller.
    if response.stop_reason == "tool_use":
        tool_block = next(b for b in response.content if b.type == "tool_use")
        if tool_block.name == "lookup_property":
            record = await lookup_property(tool_block.input["address"])
            state.property = record
            state.address_raw = tool_block.input["address"]

            follow_up = client.messages.create(
                model=settings.claude_model,
                max_tokens=300,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages
                + [
                    {"role": "assistant", "content": response.content},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_block.id,
                                "content": json.dumps(record.model_dump()),
                            }
                        ],
                    },
                ],
            )
            reply_text = _extract_text(follow_up)
        else:
            reply_text = _extract_text(response)
    else:
        reply_text = _extract_text(response)

    state.qa_history.append({"caller": caller_speech, "receptionist": reply_text})
    return reply_text


def _build_message_history(state: CallState, caller_speech: str) -> list[dict]:
    messages = []
    for turn in state.qa_history:
        messages.append({"role": "assistant", "content": turn["receptionist"]})
        messages.append({"role": "user", "content": turn["caller"]})
    messages.append({"role": "user", "content": caller_speech})
    return messages


def _extract_text(response) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text
    return "Sorry, could you say that again?"


def score_lead(state: CallState) -> tuple[int, LeadStatus]:
    """Rule-based scoring, same base+signals approach as Speed-to-Lead's
    n8n scorer, so both channels are tunable the same way."""
    score = 40  # base, matches speed-to-lead-qualifier.json convention

    if len(state.qa_history) >= 6:  # all 6 questions answered
        score += 30

    text_blob = " ".join(t["caller"].lower() for t in state.qa_history)

    if any(k in text_blob for k in ["emergency", "asap", "urgent", "leak", "this week"]):
        score += 15
    if any(k in text_blob for k in ["just pricing", "just looking", "not sure", "exploring"]):
        score -= 15
    if state.property and state.property.lookup_succeeded:
        score += 5  # verified property data is a positive signal
    if state.is_owner_match is False:
        score -= 40  # renter — should already be closed out by the agent, belt & suspenders

    score = max(0, min(100, score))

    if score >= settings.qualify_score_threshold:
        status = LeadStatus.HOT
    elif score >= 55:
        status = LeadStatus.WARM
    else:
        status = LeadStatus.NURTURE

    state.lead_score = score
    state.lead_status = status
    return score, status
