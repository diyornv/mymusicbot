"""
Main bot module – @BASS_MIDAS Channel Audio Processor
=====================================================
Listens for audio posts in the configured channel, rewrites metadata
(title, performer, cover art), re-uploads, and deletes the original.
Audio content is NOT modified.
"""

import asyncio
import io
import logging
import shutil
import time as _time
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BufferedInputFile, FSInputFile
from PIL import Image

import config
from metadata import process_audio

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bass_midas_bot")

# ── Bot & Dispatcher ────────────────────────────────────────────────────────

bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# ── Startup timestamp ────────────────────────────────────────────────────────

_boot_timestamp: int = 0

# ── Thumbnail cache ─────────────────────────────────────────────────────────

_thumb_bytes: bytes | None = None


def _make_thumbnail(cover_path: Path) -> bytes:
    global _thumb_bytes
    if _thumb_bytes is not None:
        return _thumb_bytes

    img = Image.open(cover_path)
    img = img.convert("RGB")
    img.thumbnail((320, 320), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    if buf.tell() > 200_000:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60, optimize=True)

    _thumb_bytes = buf.getvalue()
    logger.info("Thumbnail: %d bytes, %dx%d", len(_thumb_bytes), img.width, img.height)
    return _thumb_bytes


def _is_already_branded(audio: types.Audio) -> bool:
    """Check if audio was already processed by us."""
    performer = (audio.performer or "").strip()
    filename = (audio.file_name or "").strip()
    title = (audio.title or "").strip()
    return (
        performer == "@BASS_MIDAS"
        or "@BASS_MIDAS" in filename
        or "@BASS_MIDAS" in title
    )


# ── Handler ──────────────────────────────────────────────────────────────────

@dp.channel_post(F.audio)
async def handle_channel_audio(message: types.Message) -> None:
    if message.chat.id != config.CHANNEL_ID:
        return

    audio = message.audio
    if audio is None:
        return

    # Guard 1: Skip old messages
    msg_date = int(message.date.timestamp()) if message.date else 0
    if msg_date < _boot_timestamp:
        return

    # Guard 2: Skip already branded
    if _is_already_branded(audio):
        return

    file_id = audio.file_id
    original_filename = audio.file_name or f"{file_id}.mp3"
    tg_title = audio.title or ""

    logger.info(
        ">>> New audio: '%s' | title='%s' | performer='%s'",
        original_filename, tg_title, audio.performer or "",
    )

    work_dir = config.TMP_DIR / file_id
    work_dir.mkdir(parents=True, exist_ok=True)

    if not original_filename.lower().endswith(".mp3"):
        original_filename += ".mp3"
    download_path = work_dir / original_filename

    try:
        # 1. Download
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, destination=download_path)
        logger.info("Downloaded: %s (%d bytes)", download_path.name, download_path.stat().st_size)

        # 2. Process metadata only (no audio modification)
        clean_title, modified_path = await process_audio(
            download_path, config.COVER_FILE, tg_title
        )
        logger.info("Title: '%s' → File: '%s'", clean_title, modified_path.name)

        # 3. Display values
        display_performer = "@BASS_MIDAS"
        display_title = clean_title

        # 4. Thumbnail
        thumb_data = _make_thumbnail(config.COVER_FILE)
        thumb_input = BufferedInputFile(thumb_data, filename="thumb.jpg")

        # 5. Re-upload with retry on flood control
        audio_file = FSInputFile(path=str(modified_path), filename=modified_path.name)
        duration = audio.duration or 0
        caption = message.caption or ""

        sent_msg = await _send_with_retry(
            audio_file, thumb_input, display_title, display_performer,
            duration, caption,
        )
        logger.info("Re-uploaded (msg_id=%d) → '%s – %s'",
                     sent_msg.message_id, display_performer, display_title)

        # 6. Delete original
        try:
            await message.delete()
            logger.info("Original (id=%d) deleted.", message.message_id)
        except Exception as e:
            logger.warning("Could not delete original: %s", e)

    except Exception:
        logger.exception("FAILED '%s'. Original left untouched.", original_filename)
    finally:
        try:
            shutil.rmtree(work_dir)
        except OSError:
            pass


async def _send_with_retry(
    audio_file, thumb_input, title, performer, duration, caption,
    max_retries: int = 3,
) -> types.Message:
    """Send audio with automatic retry on Telegram flood control."""
    for attempt in range(max_retries):
        try:
            return await bot.send_audio(
                chat_id=config.CHANNEL_ID,
                audio=audio_file,
                thumbnail=thumb_input,
                title=title,
                performer=performer,
                duration=duration,
                caption=caption,
            )
        except TelegramRetryAfter as e:
            wait = e.retry_after + 1
            logger.warning(
                "Flood control! Waiting %d seconds (attempt %d/%d)...",
                wait, attempt + 1, max_retries,
            )
            await asyncio.sleep(wait)
            # Re-create the input file since it may have been consumed
            if hasattr(audio_file, 'path'):
                audio_file = FSInputFile(path=audio_file.path, filename=audio_file.filename)
            thumb_input = BufferedInputFile(_make_thumbnail(config.COVER_FILE), filename="thumb.jpg")
    # Last attempt — let exception propagate
    return await bot.send_audio(
        chat_id=config.CHANNEL_ID,
        audio=audio_file,
        thumbnail=thumb_input,
        title=title,
        performer=performer,
        duration=duration,
        caption=caption,
    )


# ── Entry point ─────────────────────────────────────────────────────────────

async def main() -> None:
    global _boot_timestamp
    config.validate()

    _boot_timestamp = int(_time.time())
    _make_thumbnail(config.COVER_FILE)

    logger.info("@BASS_MIDAS bot starting...")
    logger.info("  Channel: %s", config.CHANNEL_ID)
    logger.info("  Boot:    %d", _boot_timestamp)

    # Drain ALL pending updates
    await bot.delete_webhook(drop_pending_updates=True)
    drained = 0
    while True:
        updates = await bot.get_updates(offset=-1, limit=1)
        if not updates:
            break
        last_id = updates[-1].update_id
        await bot.get_updates(offset=last_id + 1, limit=1)
        drained += 1
        if drained > 500:
            break

    logger.info("  Drained %d pending update(s).", drained)
    await dp.start_polling(bot, allowed_updates=["channel_post"])


if __name__ == "__main__":
    asyncio.run(main())
