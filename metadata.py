"""
Audio metadata module.
Strips foreign watermarks from titles, updates ID3 tags (title + cover art),
and renames the file with @BASS_MIDAS branding.
Audio content is NOT modified — only metadata changes.
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
    for ch in r'<>:"/\|?*':
        name = name.replace(ch, "")
    return " ".join(name.split()).strip()


def strip_watermarks(text: str, allow_empty: bool = False) -> str:
    """
    Remove ALL foreign channel watermarks from a string.
    """
    cleaned = text.strip()
    cleaned = re.sub(r't\.me/\S+', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'@(?!BASS_MIDAS)\S+', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^[\s\-–—|:]+', '', cleaned)
    cleaned = re.sub(r'[\s\-–—|:]+$', '', cleaned)
    cleaned = re.sub(r'\(\s*\)', '', cleaned)
    cleaned = " ".join(cleaned.split()).strip()

    if cleaned:
        return cleaned
    elif allow_empty:
        return ""
    else:
        return text.strip()


def _process_tags(
    audio_path: Path,
    cover_path: Path,
    tg_title: str,
) -> tuple[str, Path]:
    """
    Processing pipeline (metadata only, audio untouched):
      1. Determine and clean the title.
      2. Update ID3 tags (title + cover).
      3. Rename the file.
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

    # ── Strip watermarks ─────────────────────────────────────────────────
    clean_title = strip_watermarks(raw_title)
    clean_title = re.sub(
        r'@BASS_MIDAS\s*[-–—]?\s*', '', clean_title, flags=re.IGNORECASE
    ).strip()

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

        tags.delall("TIT2")
        tags.add(TIT2(encoding=3, text=[new_title]))

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
        logger.warning("Cannot modify ID3: %s — skipping.", e)

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
    audio_path: Path,
    cover_path: Path,
    tg_title: str = "",
) -> tuple[str, Path]:
    return await asyncio.to_thread(
        _process_tags, audio_path, cover_path, tg_title
    )
