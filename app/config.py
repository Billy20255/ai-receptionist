"""
Central config. Everything reads from environment variables (.env locally,
real env vars in production). Nothing here should be hardcoded per-client —
swap the .env file to reuse this whole service for a new client/county.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Anthropic
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    # Property lookup
    county_parcel_feature_service_url: str = (
        "https://gis.broward.org/arcgis/rest/services/OpenData/Parcels/MapServer/0"
    )
    geocoder_base_url: str = "https://geocoding.geo.census.gov/geocoder"

    # Calendar
    google_calendar_id: str = "primary"
    google_service_account_json_path: str = "./google-service-account.json"

    # Dispatch
    dispatch_channel: str = "sms"  # sms | slack | email
    dispatch_sms_to: str = ""
    slack_webhook_url: str = ""
    dispatch_email_to: str = ""

    # App
    app_base_url: str = "http://localhost:8000"
    qualify_score_threshold: int = 75


settings = Settings()
