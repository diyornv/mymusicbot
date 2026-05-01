"""
Main bot module – @BASS_MIDAS Channel Audio Processor
=====================================================
Listens for audio posts in the configured channel, rewrites metadata,
re-uploads with branding, and deletes the original.
"""

import io
import logging
import shutil
import time as _time
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
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

# ── Startup timestamp — ignore all messages sent before bot starts ───────────

_boot_timestamp: int = 0

# ── Thumbnail cache ─────────────────────────────────────────────────────────

_thumb_bytes: bytes | None = None


def _make_thumbnail(cover_path: Path) -> bytes:
    """
    Convert cover image to JPEG thumbnail for Telegram.
    Requirements: JPEG format, <200 KB, max 320x320 pixels.
    """
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
    """
    Check if this audio was already processed by us.
    We check multiple signals to be absolutely sure:
    - performer == "@BASS_MIDAS"
    - filename contains "@BASS_MIDAS"
    - title contains "@BASS_MIDAS"
    """
    performer = (audio.performer or "").strip()
    filename = (audio.file_name or "").strip()
    title = (audio.title or "").strip()

    if performer == "@BASS_MIDAS":
        return True
    if "@BASS_MIDAS" in filename:
        return True
    if "@BASS_MIDAS" in title:
        return True
    return False


# ── Handler: channel audio messages ─────────────────────────────────────────

@dp.channel_post(F.audio)
async def handle_channel_audio(message: types.Message) -> None:
    """
    Triggered on every audio post in the target channel.
    Pipeline: download → edit tags → re-upload → delete original → cleanup.
    """
    # Only process messages from the configured channel
    if message.chat.id != config.CHANNEL_ID:
        return

    audio = message.audio
    if audio is None:
        return

    # *** GUARD 1: Skip old messages from before bot started ***
    msg_date = int(message.date.timestamp()) if message.date else 0
    if msg_date < _boot_timestamp:
        logger.debug("Skipping old message (date=%d < boot=%d)", msg_date, _boot_timestamp)
        return

    # *** GUARD 2: Skip messages already branded by us ***
    if _is_already_branded(audio):
        logger.debug("Skipping already-branded audio: '%s'", audio.file_name or audio.title)
        return

    file_id = audio.file_id
    original_filename = audio.file_name or f"{file_id}.mp3"
    tg_title = audio.title or ""
    tg_performer = audio.performer or ""

    logger.info(
        ">>> New audio: file='%s' | title='%s' | performer='%s' | size=%s",
        original_filename, tg_title, tg_performer, audio.file_size,
    )

    # Per-message temp directory
    work_dir = config.TMP_DIR / file_id
    work_dir.mkdir(parents=True, exist_ok=True)

    if not original_filename.lower().endswith(".mp3"):
        original_filename += ".mp3"
    download_path = work_dir / original_filename

    try:
        # ── 1. Download ──────────────────────────────────────────────────
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, destination=download_path)
        logger.info("Downloaded: %s (%d bytes)", download_path.name, download_path.stat().st_size)

        # ── 2. Process metadata ──────────────────────────────────────────
        clean_title, modified_path = await process_audio(
            download_path, config.COVER_FILE, tg_title
        )
        logger.info("Title: '%s' → File: '%s'", clean_title, modified_path.name)

        # ── 3. Build display values ──────────────────────────────────────
        # Telegram displays audio as: "performer – title"
        # We want: "@BASS_MIDAS – {clean song title}"
        display_performer = "@BASS_MIDAS"
        display_title = clean_title

        # ── 4. Prepare thumbnail ─────────────────────────────────────────
        thumb_data = _make_thumbnail(config.COVER_FILE)
        thumb_input = BufferedInputFile(thumb_data, filename="thumb.jpg")

        # ── 5. Re-upload ─────────────────────────────────────────────────
        audio_file = FSInputFile(path=str(modified_path), filename=modified_path.name)

        duration = audio.duration or 0
        caption = message.caption or ""

        sent_msg = await bot.send_audio(
            chat_id=config.CHANNEL_ID,
            audio=audio_file,
            thumbnail=thumb_input,
            title=display_title,
            performer=display_performer,
            duration=duration,
            caption=caption,
        )

        logger.info("Re-uploaded (msg_id=%d) → '%s – %s'",
                     sent_msg.message_id, display_performer, display_title)

        # ── 6. Delete original ───────────────────────────────────────────
        try:
            await message.delete()
            logger.info("Original message (id=%d) deleted.", message.message_id)
        except Exception as e:
            logger.warning("Could not delete original: %s", e)

    except Exception:
        logger.exception("FAILED to process '%s'. Original left untouched.", original_filename)
    finally:
        # ── 7. Cleanup ───────────────────────────────────────────────────
        try:
            shutil.rmtree(work_dir)
            logger.info("Temp cleaned.")
        except OSError as e:
            logger.warning("Cleanup error: %s", e)


# ── Entry point ─────────────────────────────────────────────────────────────

async def main() -> None:
    global _boot_timestamp

    config.validate()

    # Record boot time — we will ignore ALL messages dated before this
    _boot_timestamp = int(_time.time())

    # Pre-generate thumbnail at startup
    _make_thumbnail(config.COVER_FILE)

    logger.info("@BASS_MIDAS bot starting...")
    logger.info("  Channel:   %s", config.CHANNEL_ID)
    logger.info("  Cover:     %s", config.COVER_FILE)
    logger.info("  Boot time: %d (ignoring older messages)", _boot_timestamp)

    # Clear ALL pending updates before starting to poll
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=["channel_post"])


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
