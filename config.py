import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    tz: str = os.environ.get("TZ", "Africa/Nairobi")

settings = Settings()
if not settings.token:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing in .env")
