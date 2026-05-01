"""
Configuration module.
Loads and validates all environment variables required by the bot.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Required settings ────────────────────────────────────────────────────────

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
CHANNEL_ID: int = int(os.getenv("CHANNEL_ID", "0"))
COVER_IMAGE_PATH: str = os.getenv("COVER_IMAGE_PATH", "assets/channel_cover.png")
VOICE_INTRO_PATH: str = os.getenv("VOICE_INTRO_PATH", "assets/voice_intro.mp3")

# ── Derived paths ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
TMP_DIR = BASE_DIR / "tmp"
COVER_FILE = BASE_DIR / COVER_IMAGE_PATH
VOICE_INTRO_FILE = BASE_DIR / VOICE_INTRO_PATH

# ── Validation ───────────────────────────────────────────────────────────────

def validate() -> None:
    """Ensure all required configuration values are present and valid."""
    errors: list[str] = []

    if not BOT_TOKEN:
        errors.append("BOT_TOKEN is missing.  Set it in .env")

    if CHANNEL_ID == 0:
        errors.append("CHANNEL_ID is missing or zero.  Set it in .env")

    if not COVER_FILE.is_file():
        errors.append(
            f"Cover image not found at '{COVER_FILE}'.  "
            f"Place your image at '{COVER_IMAGE_PATH}' or update COVER_IMAGE_PATH in .env"
        )

    if not VOICE_INTRO_FILE.is_file():
        print(
            f"[CONFIG WARNING] Voice intro not found at '{VOICE_INTRO_FILE}'. "
            f"Voice overlay will be SKIPPED. Place your audio at '{VOICE_INTRO_PATH}'.",
            file=sys.stderr,
        )

    if errors:
        for e in errors:
            print(f"[CONFIG ERROR] {e}", file=sys.stderr)
        sys.exit(1)
