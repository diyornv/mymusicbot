"""
Audio metadata manipulation module.
Handles ID3 tag editing and cover art embedding via Mutagen.
Strips all foreign watermarks (t.me/xxx, @xxx) from titles
and replaces them with @BASS_MIDAS branding.
"""

import asyncio
import logging
import re
from pathlib import Path

from mutagen.id3 import ID3, APIC, TIT2, ID3NoHeaderError
from mutagen.mp3 import MP3, HeaderNotFoundError

logger = logging.getLogger(__name__)

# ── Branding ─────────────────────────────────────────────────────────────────

CHANNEL_TAG = "@BASS_MIDAS"


def _read_cover_bytes(cover_path: Path) -> bytes:
    with open(cover_path, "rb") as f:
        return f.read()


def _detect_mime(cover_path: Path) -> str:
    ext = cover_path.suffix.lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",  ".webp": "image/webp",
    }.get(ext, "image/jpeg")


def _sanitize_filename(name: str) -> str:
    """Remove characters illegal in filenames."""
    for ch in r'<>:"/\|?*':
        name = name.replace(ch, "")
    return " ".join(name.split()).strip()


def strip_watermarks(title: str) -> str:
    """
    Remove ALL foreign channel watermarks from a title.
    Handles patterns like:
      - "t.me/Phonk_Uz – SONG NAME"
      - "t.me/Phonk_Uz - SONG NAME"
      - "@SomeChannel – SONG NAME"
      - "@SomeChannel - SONG NAME"
      - "SONG NAME | t.me/channel"
      - "SONG NAME (@channel)"
    Preserves @BASS_MIDAS if already present.
    """
    cleaned = title.strip()

    # Remove t.me/xxx links anywhere in the string
    cleaned = re.sub(r't\.me/\S+', '', cleaned, flags=re.IGNORECASE)

    # Remove @username tags (but NOT @BASS_MIDAS)
    cleaned = re.sub(r'@(?!BASS_MIDAS)\S+', '', cleaned, flags=re.IGNORECASE)

    # Remove leftover separators at the beginning: "– ", "- ", "| "
    cleaned = re.sub(r'^[\s\-–—|:]+', '', cleaned)

    # Remove leftover separators at the end: " –", " -", " |"
    cleaned = re.sub(r'[\s\-–—|:]+$', '', cleaned)

    # Remove parentheses that are now empty: "(  )"
    cleaned = re.sub(r'\(\s*\)', '', cleaned)

    # Collapse multiple spaces
    cleaned = " ".join(cleaned.split()).strip()

    return cleaned if cleaned else title.strip()


def _process_tags(audio_path: Path, cover_path: Path, tg_title: str) -> tuple[str, Path]:
    """
    1. Extract original title (from ID3 or Telegram metadata).
    2. Strip all foreign watermarks.
    3. Update ID3 tags if file is valid MP3.
    4. Rename file.
    Returns (clean_title, new_file_path).
    """
    # ── Get raw title ────────────────────────────────────────────────────
    id3_title = ""
    try:
        tags = ID3(str(audio_path))
        tit2 = tags.get("TIT2")
        if tit2 and str(tit2).strip():
            id3_title = str(tit2).strip()
    except Exception:
        pass

    raw_title = id3_title or tg_title or audio_path.stem
    logger.info("Raw title: '%s'", raw_title)

    # ── Strip all watermarks ─────────────────────────────────────────────
    clean_title = strip_watermarks(raw_title)

    # Also remove @BASS_MIDAS if it's already there (we'll re-add it)
    clean_title = re.sub(r'@BASS_MIDAS\s*[-–—]?\s*', '', clean_title, flags=re.IGNORECASE).strip()

    if not clean_title or len(clean_title) < 2:
        clean_title = audio_path.stem

    logger.info("Clean title: '%s'", clean_title)

    # ── Build new title ──────────────────────────────────────────────────
    new_title = f"{CHANNEL_TAG} - {clean_title}"

    # ── Modify ID3 tags (only if valid MP3) ──────────────────────────────
    try:
        mp3 = MP3(str(audio_path))
        logger.info("Valid MP3: %.1fs, %d bps", mp3.info.length, mp3.info.bitrate)

        try:
            tags = ID3(str(audio_path))
        except ID3NoHeaderError:
            mp3.add_tags()
            mp3.save()
            tags = ID3(str(audio_path))

        # Set title
        tags.delall("TIT2")
        tags.add(TIT2(encoding=3, text=[new_title]))

        # Replace cover art
        tags.delall("APIC")
        cover_data = _read_cover_bytes(cover_path)
        cover_mime = _detect_mime(cover_path)
        tags.add(APIC(
            encoding=3, mime=cover_mime, type=3,
            desc="Channel Cover", data=cover_data,
        ))
        tags.save(v2_version=3)
        logger.info("ID3 tags updated.")

    except (HeaderNotFoundError, Exception) as e:
        logger.warning("Cannot modify ID3 (not standard MP3): %s — skipping.", e)

    # ── Rename file ──────────────────────────────────────────────────────
    safe_title = _sanitize_filename(clean_title) or "Track"
    new_name = f"{safe_title} - {CHANNEL_TAG}.mp3"
    new_path = audio_path.parent / new_name

    if audio_path != new_path:
        if new_path.exists():
            new_path.unlink()
        audio_path.rename(new_path)

    logger.info("Renamed to: %s", new_path.name)
    return clean_title, new_path


async def process_audio(
    audio_path: Path, cover_path: Path, tg_title: str = ""
) -> tuple[str, Path]:
    return await asyncio.to_thread(_process_tags, audio_path, cover_path, tg_title)
