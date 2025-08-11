import asyncio
from typing import Iterable, Optional
from telegram import Bot, InputFile
from telegram.constants import ParseMode
from loguru import logger

# Practical throttles to stay well within Telegram limits:
# - Overall: <= 30 msgs/sec (we'll stay ~1 msg/sec)
# - Same group: <= 20 msgs/min (~1 per 3 sec) — we send only one per group per run.
# Sources: Telegram bots FAQ + community docs.
OVERALL_DELAY_SEC = 1.5  # conservative

def validate_lengths(text: str, has_media: bool) -> str:
    if not text:
        return ""
    max_len = 1024 if has_media else 4096
    if len(text) > max_len:
        logger.warning(f"Message truncated from {len(text)} to {max_len} (has_media={has_media})")
        return text[:max_len]
    return text

async def send_text(bot: Bot, chat_id: int | str, text: str):
    await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)

async def send_media(
    bot: Bot,
    chat_id: int | str,
    file_path: str,
    caption: Optional[str] = None,
):
    # Auto-detect type by extension; Telegram will infer for most common types
    lowered = file_path.lower()
    with open(file_path, "rb") as f:
        if lowered.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            await bot.send_photo(chat_id=chat_id, photo=InputFile(f), caption=caption, parse_mode=ParseMode.HTML)
        elif lowered.endswith((".mp4", ".mov", ".mkv", ".avi")):
            await bot.send_video(chat_id=chat_id, video=InputFile(f), caption=caption, parse_mode=ParseMode.HTML)
        else:
            await bot.send_document(chat_id=chat_id, document=InputFile(f), caption=caption, parse_mode=ParseMode.HTML)

async def broadcast(
    bot: Bot,
    chat_ids: Iterable[int | str],
    text: str = "",
    media_path: Optional[str] = None,
    batch_size: int = 15,
):
    # Send in batches to keep load modest and logs clear
    chat_ids = list(chat_ids)
    total = len(chat_ids)
    for i in range(0, total, batch_size):
        batch = chat_ids[i:i + batch_size]
        logger.info(f"Sending batch {i//batch_size + 1} - {len(batch)} chats")
        for cid in batch:
            try:
                if media_path:
                    cap = validate_lengths(text, has_media=True)
                    await send_media(bot, cid, media_path, cap)
                else:
                    msg = validate_lengths(text, has_media=False)
                    await send_text(bot, cid, msg)
            except Exception as e:
                logger.exception(f"Failed to send to {cid}: {e}")
            await asyncio.sleep(OVERALL_DELAY_SEC)
