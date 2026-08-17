"""
These test the parts that don't require live network calls to Twilio/GeoHub/
Anthropic — the field-mapping and normalization logic. Run before every
change to FIELD_MAP in property_lookup.py so a schema fix doesn't silently
break normalization.
"""
from app.services.property_lookup import normalize_attributes, FIELD_MAP


def test_normalize_attributes_maps_fields_correctly():
    raw_attributes = {
        FIELD_MAP["owner_name"]: "SMITH JOHN",
        FIELD_MAP["year_built"]: "1998",
        FIELD_MAP["square_footage"]: "1850.0",
        FIELD_MAP["land_use"]: "01",
        FIELD_MAP["assessed_value"]: "425000",
    }
    record = normalize_attributes("123 Main St", raw_attributes)

    assert record.address == "123 Main St"
    assert record.owner_name == "SMITH JOHN"
    assert record.year_built == 1998
    assert record.square_footage == 1850.0
    assert record.assessed_value == 425000.0
    assert record.lookup_succeeded is True


def test_normalize_attributes_handles_missing_fields_gracefully():
    record = normalize_attributes("456 Oak Ave", {})

    assert record.owner_name is None
    assert record.year_built is None
    assert record.lookup_succeeded is True  # normalization itself succeeded, data is just sparse


def test_normalize_attributes_handles_malformed_numbers():
    raw_attributes = {
        FIELD_MAP["year_built"]: "not-a-year",
        FIELD_MAP["square_footage"]: None,
    }
    record = normalize_attributes("789 Pine Rd", raw_attributes)

    assert record.year_built is None
    assert record.square_footage is None
