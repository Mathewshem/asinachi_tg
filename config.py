import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Optional: read from st.secrets when running on Streamlit Cloud
try:
    import streamlit as st
    _secrets = st.secrets
except Exception:
    _secrets = {}

load_dotenv()

@dataclass
class Settings:
    token: str = _secrets.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    tz: str = _secrets.get("TZ", os.environ.get("TZ", "Africa/Nairobi"))

settings = Settings()
if not settings.token:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing (set in Streamlit Secrets or .env)")
