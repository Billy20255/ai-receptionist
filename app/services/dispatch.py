"""
Sends the "go do the in-person presentation" notification to the sales team,
per the project notes' step 7. Channel is configurable per client
(DISPATCH_CHANNEL) since different businesses live in SMS vs. Slack vs. email.
"""
from __future__ import annotations

import httpx
from twilio.rest import Client as TwilioClient

from app.config import settings
from app.models import CallState


def _format_dispatch_message(state: CallState) -> str:
    prop = state.property
    lines = [
        f"HOT LEAD — score {state.lead_score}",
        f"Phone: {state.from_number}",
        f"Address: {state.address_raw or 'not captured'}",
    ]
    if prop and prop.lookup_succeeded:
        lines.append(f"Owner on record: {prop.owner_name or 'unknown'}")
        lines.append(f"Year built: {prop.year_built or 'unknown'}")
        lines.append(f"Sq ft: {prop.square_footage or 'unknown'}")
    if state.booked_slot:
        lines.append(f"Booked: {state.booked_slot}")
    return "\n".join(lines)


def send_dispatch_notification(state: CallState) -> None:
    message = _format_dispatch_message(state)

    if settings.dispatch_channel == "sms" and settings.dispatch_sms_to:
        _send_sms(message)
    elif settings.dispatch_channel == "slack" and settings.slack_webhook_url:
        _send_slack(message)
    elif settings.dispatch_channel == "email" and settings.dispatch_email_to:
        _send_email(message)
    # Silent no-op if not configured — don't fail the call over a
    # misconfigured dispatch channel; log this in real deployment.


def _send_sms(message: str) -> None:
    client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    client.messages.create(
        to=settings.dispatch_sms_to,
        from_=settings.twilio_phone_number,
        body=message,
    )


def _send_slack(message: str) -> None:
    httpx.post(settings.slack_webhook_url, json={"text": message}, timeout=10)


def _send_email(message: str) -> None:
    # Stub — plug in whatever transactional email provider the client already
    # uses (SendGrid, Postmark, etc.). Left unimplemented deliberately since
    # this varies per client and isn't core to the pilot.
    raise NotImplementedError(
        "Email dispatch not wired yet — use sms or slack for the pilot, "
        "or implement this against your provider of choice."
    )
