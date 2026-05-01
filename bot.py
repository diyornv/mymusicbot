"""
Main bot module – @BASS_MIDAS Channel Audio Processor
=====================================================
Listens to a configured Telegram channel for audio messages,
rewrites their ID3 metadata + cover art, re-uploads the modified
file, and deletes the original post.

Usage:
    python bot.py
"""

import asyncio
import logging
import shutil
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile

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


# ── Handler: channel audio messages ─────────────────────────────────────────

@dp.channel_post(F.audio)
async def handle_channel_audio(message: types.Message) -> None:
    """
    Triggered every time an audio file is posted in the target channel.
    Pipeline: download → edit tags → re-upload → delete original → cleanup.
    """
    # Only process messages from the configured channel
    if message.chat.id != config.CHANNEL_ID:
        logger.debug(
            "Ignoring audio from chat %s (not target channel %s)",
            message.chat.id,
            config.CHANNEL_ID,
        )
        return

    audio = message.audio
    if audio is None:
        return

    file_id = audio.file_id
    original_filename = audio.file_name or f"{file_id}.mp3"
    logger.info(
        "📥 New audio detected: '%s' (file_id=%s, size=%s bytes)",
        original_filename,
        file_id,
        audio.file_size,
    )

    # Create a per-message temp directory to avoid filename collisions
    work_dir = config.TMP_DIR / file_id
    work_dir.mkdir(parents=True, exist_ok=True)
    download_path = work_dir / original_filename

    try:
        # ── 1. Download ──────────────────────────────────────────────────
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, destination=download_path)
        logger.info("✅ Downloaded to %s", download_path)

        # ── 2. Process metadata (runs in thread) ────────────────────────
        original_title, modified_path = await process_audio(
            download_path, config.COVER_FILE
        )
        logger.info("✅ Metadata processed. New file: %s", modified_path.name)

        # ── 3. Re-upload ────────────────────────────────────────────────
        input_file = FSInputFile(path=str(modified_path), filename=modified_path.name)

        # Read the cover to attach as thumbnail
        thumb_file = FSInputFile(path=str(config.COVER_FILE))

        # Preserve original caption / performer if present
        performer = audio.performer or ""
        duration = audio.duration or 0
        caption = message.caption or ""

        await bot.send_audio(
            chat_id=config.CHANNEL_ID,
            audio=input_file,
            thumbnail=thumb_file,
            title=f"@BASS_MIDAS - {original_title}",
            performer=performer,
            duration=duration,
            caption=caption,
        )
        logger.info("✅ Modified audio re-uploaded to channel.")

        # ── 4. Delete original message ───────────────────────────────────
        await message.delete()
        logger.info("🗑️  Original message deleted.")

    except Exception:
        logger.exception(
            "❌ Failed to process audio '%s' (file_id=%s). "
            "The original message was left untouched.",
            original_filename,
            file_id,
        )
    finally:
        # ── 5. Cleanup temp files ────────────────────────────────────────
        try:
            shutil.rmtree(work_dir)
            logger.info("🧹 Temp directory cleaned: %s", work_dir)
        except OSError as exc:
            logger.warning("Could not remove temp dir %s: %s", work_dir, exc)


# ── Entry point ─────────────────────────────────────────────────────────────

async def main() -> None:
    """Validate config, skip pending updates, and start long-polling."""
    config.validate()
    logger.info("🚀 @BASS_MIDAS bot is starting…")
    logger.info("   Channel ID : %s", config.CHANNEL_ID)
    logger.info("   Cover image: %s", config.COVER_FILE)

    # Drop pending updates so we don't re-process old messages on restart
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
