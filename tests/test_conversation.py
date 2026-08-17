from app.models import CallState, LeadStatus, PropertyRecord
from app.services.conversation import score_lead


def _state_with_history(caller_lines: list[str], property_found: bool = True) -> CallState:
    state = CallState(call_sid="CA123", from_number="+19545550100")
    state.qa_history = [{"caller": line, "receptionist": "ok"} for line in caller_lines]
    if property_found:
        state.property = PropertyRecord(address="123 Main St", lookup_succeeded=True)
    return state


def test_hot_lead_all_questions_urgent_timeline():
    caller_lines = [
        "There's a leak in the roof",
        "roof is about 15 years old",
        "yes I own the home",
        "yes insurance is involved",
        "this is an emergency, need someone this week",
        "yes I'm the one deciding",
    ]
    state = _state_with_history(caller_lines)
    score, status = score_lead(state)

    assert status == LeadStatus.HOT
    assert score >= 75


def test_low_intent_lead_scores_lower():
    caller_lines = [
        "just checking things out",
        "roof is pretty old",
        "yes I own it",
        "no insurance",
        "just pricing, not sure yet, exploring options",
        "yes",
    ]
    state = _state_with_history(caller_lines)
    score, status = score_lead(state)

    assert status != LeadStatus.HOT
    assert score < 75


def test_renter_owner_mismatch_is_penalized():
    state = _state_with_history(["I rent this place"] * 6)
    state.is_owner_match = False
    score, status = score_lead(state)

    assert status == LeadStatus.NURTURE
    assert score < 55


def test_incomplete_call_scores_lower_than_complete_one():
    incomplete = _state_with_history(["there's damage", "not sure how old"])
    complete = _state_with_history(
        ["there's damage", "not sure how old", "yes own", "no", "soon", "yes"]
    )
    incomplete_score, _ = score_lead(incomplete)
    complete_score, _ = score_lead(complete)

    assert complete_score > incomplete_score
