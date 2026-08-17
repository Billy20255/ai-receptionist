"""
Shared data shapes. Kept deliberately small — this mirrors the same fields
Speed-to-Lead already logs (name, phone, business, Q1-Q5, score, status) so
both channels can eventually write into the same CRM record shape.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class LeadStatus(str, Enum):
    HOT = "HOT"
    WARM = "WARM"
    NURTURE = "NURTURE"
    DISQUALIFIED = "DISQUALIFIED"


class PropertyRecord(BaseModel):
    """Normalized shape regardless of which county's GIS schema it came from.
    Field-name mapping per county happens in property_lookup.py, not here —
    this is the stable contract the rest of the app relies on."""

    address: str
    owner_name: Optional[str] = None
    year_built: Optional[int] = None
    square_footage: Optional[float] = None
    land_use: Optional[str] = None
    assessed_value: Optional[float] = None
    county: Optional[str] = None
    raw_source_fields: dict = Field(default_factory=dict)
    lookup_succeeded: bool = False


class CallState(BaseModel):
    """In-memory state for one active call, keyed by Twilio CallSid.
    For a real pilot this can stay in-memory (single instance); move to
    Redis/DB before attempting multi-tenant scale, per the spec's own
    sequencing note."""

    call_sid: str
    from_number: str
    address_raw: Optional[str] = None
    property: Optional[PropertyRecord] = None
    qa_history: list[dict] = Field(default_factory=list)  # [{"question":..., "answer":...}]
    turn_count: int = 0
    is_owner_match: Optional[bool] = None
    lead_score: int = 0
    lead_status: Optional[LeadStatus] = None
    booked_slot: Optional[str] = None


class QualifyingAnswers(BaseModel):
    """The 6 questions from the project notes, structured."""

    issue_type: Optional[str] = None          # leak / damage / quote-only
    roof_or_window_age: Optional[str] = None
    is_homeowner: Optional[bool] = None
    insurance_claim: Optional[bool] = None
    timeline: Optional[str] = None             # emergency / weeks / just quotes
    is_decision_maker: Optional[bool] = None
