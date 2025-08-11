import asyncio
import json
from datetime import time, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import threading
from telegram.request import HTTPXRequest


import streamlit as st
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from telegram import Bot

# Try to use HTTPXRequest if the installed PTB supports it
try:
    from telegram.request import HTTPXRequest
    HAVE_HTTPX = True
except Exception:
    HTTPXRequest = None
    HAVE_HTTPX = False

from config import settings
from tg_client import broadcast

# ── Paths & setup ──────────────────────────────────────────────────────────────
DATA_DIR = Path("data")
UPLOADS_DIR = DATA_DIR / "uploads"
TARGETS_FILE = DATA_DIR / "chat_targets.json"
MESSAGE_FILE = DATA_DIR / "message.json"
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
SEND_LOCK = threading.Lock()

logger.add(LOG_DIR / "app.log", rotation="1 MB")

TZ = ZoneInfo(settings.tz)

# ── Persistence helpers (file-based, not session_state) ───────────────────────
def load_targets():
    if TARGETS_FILE.exists():
        return json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    return {"chat_ids": [], "default_batch_size": 15}

def save_targets(d):
    TARGETS_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")

def load_message():
    if MESSAGE_FILE.exists():
        return json.loads(MESSAGE_FILE.read_text(encoding="utf-8"))
    return {"text": "", "media_path": None}

def save_message(text: str, media_path: str | None):
    MESSAGE_FILE.write_text(json.dumps({"text": text, "media_path": media_path}, indent=2), encoding="utf-8")

# ── Cached bot & scheduler ─────────────────────────────────────────────────────
def make_bot() -> Bot:
    if HAVE_HTTPX:
        req = HTTPXRequest(
            connect_timeout=10.0,
            read_timeout=60.0,
            write_timeout=10.0,
            pool_timeout=10.0,
            connection_pool_size=50,
        )
        return Bot(token=settings.token, request=req)
    # Fallback: default request client (works, just fewer pool controls)
    return Bot(token=settings.token)


@st.cache_resource
def get_scheduler():
    # thread-based scheduler (no asyncio event loop required)
    sched = BackgroundScheduler(timezone=TZ)
    sched.start()
    return sched

# ── Sending helpers (sync wrapper that runs async) ─────────────────────────────
def run_broadcast_now(message_text: str, media_path: str | None, batch_size: int, chat_ids: list):
    """
    Safe to call from Streamlit or scheduler threads.
    Creates a fresh Bot with a roomy HTTP pool and ensures only one send runs at a time.
    """
    async def _runner():
        # Ensure connections are closed after use
        async with make_bot() as bot:
            await broadcast(bot, chat_ids=chat_ids, text=message_text, media_path=media_path, batch_size=batch_size)

    with SEND_LOCK:
        asyncio.run(_runner())

def job_runner_sync(phase: int, batch_size: int):
    cfg = load_targets()
    chat_ids: list = cfg.get("chat_ids", [])
    if not chat_ids:
        logger.warning("No chat_ids configured")
        return
    msg = load_message()
    text = msg.get("text", "")
    media_path = msg.get("media_path", None)

    # phase 1 = first N ; phase 2 = remainder
    if phase == 1:
        ids = chat_ids[:batch_size]
    else:
        ids = chat_ids[batch_size:]

    if not ids:
        logger.info(f"No targets for phase {phase}")
        return

    logger.info(f"Scheduled phase {phase} → {len(ids)} chats @ {datetime.now(TZ)}")
    run_broadcast_now(text, media_path, batch_size=batch_size, chat_ids=ids)

def schedule_jobs(times: list[time], second_phase_offset_min: int, batch_size: int):
    sched = get_scheduler()
    # Clear previous jobs created by this app
    for job in list(sched.get_jobs()):
        if job.name and job.name.startswith("tg_broadcast"):
            sched.remove_job(job.id)

    for t in times:
        # Phase 1
        trig1 = CronTrigger(hour=t.hour, minute=t.minute, second=0, timezone=TZ)
        sched.add_job(
            func=job_runner_sync,
            trigger=trig1,
            kwargs={"phase": 1, "batch_size": batch_size},
            name=f"tg_broadcast_phase1_{t.hour:02d}{t.minute:02d}",
            replace_existing=True
        )
        # Phase 2 (offset minutes later)
        minute2 = (t.minute + second_phase_offset_min) % 60
        hour2 = (t.hour + (t.minute + second_phase_offset_min) // 60) % 24
        trig2 = CronTrigger(hour=hour2, minute=minute2, second=0, timezone=TZ)
        sched.add_job(
            func=job_runner_sync,
            trigger=trig2,
            kwargs={"phase": 2, "batch_size": batch_size},
            name=f"tg_broadcast_phase2_{t.hour:02d}{t.minute:02d}",
            replace_existing=True
        )

# ── Streamlit UI ───────────────────────────────────────────────────────────────
def main():
    st.title("Telegram Scheduler (Compliant)")
    st.caption(f"Timezone: {settings.tz}")

    cfg = load_targets()
    msg = load_message()

    # ─ Targets ─
    st.subheader("Targets (channels/groups you manage)")
    st.write("Paste numeric chat IDs or @usernames, one per line. Add the bot to each target with rights to post.")
    raw = st.text_area(
        "Targets",
        value="\n".join(map(str, cfg.get("chat_ids", []))),
        height=150,
        help="One per line. Example: @asinachisolvestech or -1001234567890",
    )
    batch_size = st.number_input(
        "Batch size per phase",
        min_value=1, max_value=1000, value=cfg.get("default_batch_size", 15)
    )

    col_t1, col_t2 = st.columns([1,1])
    if col_t1.button("Save targets"):
        items = [x.strip() for x in raw.splitlines() if x.strip()]
        cfg["chat_ids"] = items
        cfg["default_batch_size"] = int(batch_size)
        save_targets(cfg)
        st.success(f"Saved {len(items)} target(s).")

    if col_t2.button("Reload saved targets"):
        cfg = load_targets()
        st.experimental_rerun()

    if not cfg.get("chat_ids"):
        st.warning("No targets saved yet. Enter them above and click **Save targets**.")

    # ─ Message ─
    st.subheader("Message")
    text_val = st.text_area(
        "Text (HTML allowed)",
        value=msg.get("text", ""),
        height=200,
        placeholder="Your announcement text"
    )
    upload = st.file_uploader(
        "Optional media (image/video/document)",
        type=["jpg","jpeg","png","gif","webp","mp4","mov","mkv","avi","pdf","doc","docx","zip"]
    )
    media_path = msg.get("media_path", None)
    if upload:
        out = UPLOADS_DIR / upload.name
        with open(out, "wb") as f:
            f.write(upload.getbuffer())
        media_path = str(out)
        st.success(f"Saved: {out}")

    col_m1, col_m2 = st.columns([1,1])
    if col_m1.button("Save message"):
        save_message(text_val, media_path)
        st.success("Saved message content to disk.")
    if col_m2.button("Clear saved media path"):
        save_message(text_val, None)
        st.info("Cleared media path.")

    # ─ Schedule ─
    st.subheader("Schedule")
    default_times = [time(9,0), time(14,0), time(16,0), time(21,0)]
    t1 = st.time_input("Slot 1", value=default_times[0], step=300)
    t2 = st.time_input("Slot 2", value=default_times[1], step=300)
    t3 = st.time_input("Slot 3", value=default_times[2], step=300)
    t4 = st.time_input("Slot 4", value=default_times[3], step=300)
    phase_gap = st.number_input("Second phase offset (minutes)", min_value=0, max_value=120, value=30)

    col_s1, col_s2 = st.columns([1,1])
    if col_s1.button("Apply schedule"):
        if not load_targets().get("chat_ids"):
            st.error("No targets configured. Save targets first.")
        else:
            schedule_jobs([t1, t2, t3, t4], second_phase_offset_min=int(phase_gap), batch_size=int(batch_size))
            st.success("Scheduled daily jobs.")

    # New: Send Now button right in Schedule section
    if col_s2.button("Send Now (batched)"):
        cfg_now = load_targets()
        if not cfg_now.get("chat_ids"):
            st.error("No targets configured. Save targets first.")
        else:
            msg_now = load_message()
            run_broadcast_now(
                message_text=msg_now.get("text",""),
                media_path=msg_now.get("media_path", None),
                batch_size=int(cfg_now.get("default_batch_size", 15)),
                chat_ids=cfg_now["chat_ids"],
            )
            st.success("Sent now. Check your channels/groups.")

    # ─ Separate Test section (kept) ─
    st.subheader("Test")
    if st.button("Send test now (all targets)"):
        cfg_now = load_targets()
        if not cfg_now.get("chat_ids"):
            st.error("No targets configured. Save targets first.")
        else:
            msg_now = load_message()
            run_broadcast_now(
                message_text=msg_now.get("text",""),
                media_path=msg_now.get("media_path", None),
                batch_size=int(cfg_now.get("default_batch_size", 15)),
                chat_ids=cfg_now["chat_ids"],
            )
            st.success("Test run complete. Check your channels/groups.")

if __name__ == "__main__":
    main()
