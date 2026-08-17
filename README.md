# AI Receptionist / Dispatch — MVP

Phone-in AI receptionist for home-services sales (impact windows / roofing).
Caller states an address → property looked up automatically → qualifying
questions asked → hot leads booked on the calendar + dispatched to the sales
team. Built per the architecture already scoped: **Skill (domain knowledge)
→ FastAPI service (Claude Agent SDK pattern) → Twilio (telephony)**.

## Status: working MVP skeleton, verified offline

What's been **built and tested** (see `tests/`, all passing):
- Lead scoring logic (base + signals, same convention as the Speed-to-Lead
  n8n scorer)
- Property record normalization (raw county GIS fields → stable schema)
- Full Twilio webhook loop (`/voice` → `/voice/gather` → booking/dispatch),
  verified with FastAPI's TestClient — produces valid TwiML end to end

What's **not yet live-tested** (needs real credentials / a real Twilio
number, can't be done from a sandboxed build environment):
- An actual phone call through Twilio
- A real Claude API call (wiring is in place, no live key was used to build this)
- A real query against Broward's GeoHub parcel layer
- A real Google Calendar booking

## Before you make your first real test call

1. **Confirm the GeoHub field names.** `app/services/property_lookup.py`
   has a `FIELD_MAP` with the common ArcGIS parcel-layer field names
   (`OWN_NAME`, `YR_BLT`, etc.) — these are NOT confirmed against Broward's
   actual schema yet. Hit
   `COUNTY_PARCEL_FEATURE_SERVICE_URL + "?f=json"` directly in a browser,
   read the real `fields` list back, and fix `FIELD_MAP` if it differs.
   This is a one-line edit per field, not a rewrite.

2. **Get a Twilio number and point it at this app.** In the Twilio console,
   set the phone number's "A call comes in" webhook to
   `https://your-deployed-domain.com/voice`, method POST. You need this app
   deployed somewhere with a public HTTPS URL first (see Deployment below).

3. **Get an Anthropic API key** and set `ANTHROPIC_API_KEY` in `.env`.

4. **Set up a Google service account** for Calendar access if you want real
   booking (see Google Cloud Console → Service Accounts → share your
   calendar with the service account's email). Without this, the app still
   works — it just tells the caller "we'll call you back to confirm a time"
   instead of booking automatically.

5. **Set your dispatch channel** — `DISPATCH_CHANNEL=sms` is the fastest to
   test since it reuses your Twilio credentials; Slack is one webhook URL
   away if you'd rather use that.

## Local setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# fill in .env with real values

uvicorn app.main:app --reload
```

Health check: `curl http://localhost:8000/health`

## Testing without a phone call

You can exercise the whole loop without Twilio or a live Anthropic key using
FastAPI's TestClient — see the pattern used to verify this build:

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.post("/voice", data={"CallSid": "CA_test", "From": "+19545550100"})
print(r.text)  # real TwiML output
```

For a true live test, you need `ngrok` (or similar) to expose localhost
publicly so Twilio can reach it:

```bash
ngrok http 8000
# then set the Twilio number's webhook to the ngrok https URL + /voice
```

## Deployment

Any host that runs a long-lived Python process works (Railway, Render,
Fly.io, a small VPS). Requirements:
- Public HTTPS URL (Twilio requires this for webhooks)
- `ANTHROPIC_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` set as real
  environment variables, not committed to the repo
- `google-service-account.json` uploaded securely if using real Calendar booking

## Architecture notes (why it's built this way)

- **In-memory call state** (`_CALLS` dict in `app/main.py`) is intentional
  for a single-pilot MVP. Don't add Redis/a database before you actually
  have concurrent multi-tenant call volume — that's explicitly a "longer
  tail" item per the original project scoping, not a Phase 1 concern.
- **`<Gather>` speech-to-text, not Media Streams.** Twilio transcribes each
  utterance and POSTs text back to us — simpler to build and debug than a
  raw audio stream, at the cost of a bit more latency per turn. The
  original notes flagged voice latency/interruption handling as the
  biggest timeline variable — if that becomes a real problem in testing,
  Media Streams is the fix, but it's a genuinely bigger lift. Don't build
  it preemptively.
- **Property lookup degrades gracefully.** If geocoding or the GIS query
  fails for any reason, the agent is instructed to just ask the caller
  directly rather than crash the call — matches the fallback plan already
  decided on in the project notes.
- **Calendar backend is swappable.** `calendar_service.py` is a thin
  wrapper specifically so this can be pointed at GHL's native calendar
  later instead of Google Calendar, without touching `main.py`, once/if
  the client side of this moves to a GHL snapshot.

## What's genuinely not done yet (don't assume otherwise)

- Email dispatch (`dispatch.py`) is an explicit `NotImplementedError` stub
  — use SMS or Slack for the pilot.
- No CRM write-back yet (`_finalize_call` in `main.py` has a TODO) —
  decide once, up front, whether the pilot writes to a Google Sheet or
  directly into a GHL sub-account, rather than building both.
- No retry/backoff on the Anthropic or GeoHub calls — fine for pilot
  volume, worth adding before any real scale.
- No persistent logging of full call transcripts — worth adding early
  since it's the fastest way to debug a call that went sideways.

## Next concrete steps, in order

1. Confirm `FIELD_MAP` against the real GeoHub schema (5 minutes, see above)
2. Get a Twilio trial number + ngrok, make one real test call to yourself
3. Fix whatever breaks in that first real call (there will be something —
   that's what Phase 4 "testing and hardening" in the original scoping was
   budgeted for)
4. Wire `_finalize_call` to write somewhere real (Sheet or GHL)
5. Pilot with one contractor before pricing it as a product, per the
   existing plan
