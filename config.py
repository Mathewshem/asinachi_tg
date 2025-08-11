import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Try to import st.secrets if running on Streamlit Cloud
try:
    import streamlit as st
    secrets = st.secrets
except ImportError:
    secrets = {}

load_dotenv()

@dataclass
class Settings:
    token: str = secrets.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    tz: str = secrets.get("TZ", os.environ.get("TZ", "Africa/Nairobi"))

settings = Settings()
if not settings.token:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing (check Streamlit Secrets or .env)")
