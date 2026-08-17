"""
Property lookup — the tool the Claude agent calls once a caller states an address.

Two steps:
  1. Geocode the raw spoken address into coordinates (Census Bureau geocoder —
     free, no key, good enough for a point-in-polygon parcel query).
  2. Query the county's ArcGIS parcel FeatureServer/MapServer layer with those
     coordinates and pull back owner/year-built/sqft/etc.

IMPORTANT — matches the open item flagged in the project notes:
The exact field names below (OWN_NAME, YR_BLT, etc.) are the common ArcGIS
parcel-layer convention but are NOT yet confirmed against Broward's actual
GeoHub schema. Before go-live: hit COUNTY_PARCEL_FEATURE_SERVICE_URL + "?f=json"
directly and read the real "fields" list back, then fix FIELD_MAP below.
This module is written so that's a one-line fix, not a rewrite.
"""
from __future__ import annotations

import httpx

from app.config import settings
from app.models import PropertyRecord

# Map our normalized field -> the source system's actual field name.
# CONFIRM AND EDIT before go-live (see docstring above).
FIELD_MAP = {
    "owner_name": "OWN_NAME",
    "year_built": "YR_BLT",
    "square_footage": "TOT_LVG_AR",
    "land_use": "DOR_UC",
    "assessed_value": "JV",
}


async def geocode_address(raw_address: str) -> tuple[float, float] | None:
    """Returns (lon, lat) or None if the address can't be resolved.
    Uses the free US Census geocoder — no API key required."""
    url = f"{settings.geocoder_base_url}/locations/onelineaddress"
    params = {
        "address": raw_address,
        "benchmark": "Public_AR_Current",
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    matches = data.get("result", {}).get("addressMatches", [])
    if not matches:
        return None

    coords = matches[0]["coordinates"]
    return coords["x"], coords["y"]  # lon, lat


async def query_parcel_by_point(lon: float, lat: float) -> dict | None:
    """Queries the configured county ArcGIS parcel layer for the parcel
    containing this point. Returns the raw attributes dict, or None."""
    url = f"{settings.county_parcel_feature_service_url}/query"
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    features = data.get("features", [])
    if not features:
        return None
    return features[0].get("attributes", {})


def normalize_attributes(raw_address: str, attributes: dict) -> PropertyRecord:
    """Maps whatever the county's raw field names are into our stable
    PropertyRecord shape, using FIELD_MAP."""
    return PropertyRecord(
        address=raw_address,
        owner_name=attributes.get(FIELD_MAP["owner_name"]),
        year_built=_safe_int(attributes.get(FIELD_MAP["year_built"])),
        square_footage=_safe_float(attributes.get(FIELD_MAP["square_footage"])),
        land_use=attributes.get(FIELD_MAP["land_use"]),
        assessed_value=_safe_float(attributes.get(FIELD_MAP["assessed_value"])),
        county="Broward",  # swap per COUNTY_PARCEL_FEATURE_SERVICE_URL in multi-county setups
        raw_source_fields=attributes,
        lookup_succeeded=True,
    )


async def lookup_property(raw_address: str) -> PropertyRecord:
    """The single entry point the Claude agent tool calls.
    Always returns a PropertyRecord — check .lookup_succeeded rather than
    catching exceptions, so a bad address degrades gracefully into
    'ask the caller directly' instead of crashing the call."""
    try:
        coords = await geocode_address(raw_address)
        if coords is None:
            return PropertyRecord(address=raw_address, lookup_succeeded=False)

        lon, lat = coords
        attributes = await query_parcel_by_point(lon, lat)
        if attributes is None:
            return PropertyRecord(address=raw_address, lookup_succeeded=False)

        return normalize_attributes(raw_address, attributes)

    except (httpx.HTTPError, httpx.TimeoutException):
        # Network/API failure — same graceful-degrade path. The agent's
        # fallback is to ask the caller directly, per the project notes.
        return PropertyRecord(address=raw_address, lookup_succeeded=False)


def _safe_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _safe_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None
