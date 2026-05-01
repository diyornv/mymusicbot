"""
Audio metadata manipulation module.
Handles ID3 tag editing and cover art embedding via Mutagen.
All heavy I/O is offloaded from the async event loop using asyncio.to_thread().
"""

import asyncio
import logging
from pathlib import Path

from mutagen.id3 import ID3, APIC, TIT2, ID3NoHeaderError
from mutagen.mp3 import MP3

logger = logging.getLogger(__name__)

# ── Branding constants ───────────────────────────────────────────────────────

CHANNEL_TAG = "@BASS_MIDAS"


def _read_cover_bytes(cover_path: Path) -> bytes:
    """Read cover image bytes from disk (synchronous helper)."""
    with open(cover_path, "rb") as f:
        return f.read()


def _detect_mime(cover_path: Path) -> str:
    """Return a MIME type string based on file extension."""
    ext = cover_path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    return mime_map.get(ext, "image/jpeg")


def _process_tags(audio_path: Path, cover_path: Path) -> tuple[str, Path]:
    """
    Synchronous, CPU/IO-bound work:
      1. Read original title (fallback to filename stem).
      2. Rewrite TIT2 → "@BASS_MIDAS - {Original Title}".
      3. Strip existing artwork and embed new cover.
      4. Rename the file to "{Original Title} - @BASS_MIDAS.mp3".
    Returns (original_title, new_file_path).
    """
    # ── Load or create ID3 header ────────────────────────────────────────
    try:
        tags = ID3(str(audio_path))
    except ID3NoHeaderError:
        # File has no ID3 header yet — create one
        mp3 = MP3(str(audio_path))
        mp3.add_tags()
        mp3.save()
        tags = ID3(str(audio_path))

    # ── Extract original title ───────────────────────────────────────────
    original_title: str = ""
    tit2 = tags.get("TIT2")
    if tit2 and str(tit2).strip():
        original_title = str(tit2).strip()
    else:
        # Fallback: derive from file name (without extension)
        original_title = audio_path.stem
    logger.info("Original title resolved to: %s", original_title)

    # ── Update title tag ─────────────────────────────────────────────────
    new_title = f"{CHANNEL_TAG} - {original_title}"
    tags.delall("TIT2")
    tags.add(TIT2(encoding=3, text=[new_title]))

    # ── Replace cover art ────────────────────────────────────────────────
    # Remove every existing APIC frame
    tags.delall("APIC")

    cover_data = _read_cover_bytes(cover_path)
    cover_mime = _detect_mime(cover_path)
    tags.add(
        APIC(
            encoding=3,          # UTF-8
            mime=cover_mime,
            type=3,              # Cover (front)
            desc="Channel Cover",
            data=cover_data,
        )
    )
    tags.save(v2_version=3)
    logger.info("ID3 tags updated successfully.")

    # ── Rename the physical file ─────────────────────────────────────────
    safe_title = _sanitize_filename(original_title)
    new_name = f"{safe_title} - {CHANNEL_TAG}.mp3"
    new_path = audio_path.parent / new_name
    audio_path.rename(new_path)
    logger.info("File renamed to: %s", new_path.name)

    return original_title, new_path


def _sanitize_filename(name: str) -> str:
    """Remove characters that are illegal in Windows/Linux filenames."""
    illegal = r'<>:"/\|?*'
    for ch in illegal:
        name = name.replace(ch, "")
    # Collapse whitespace
    return " ".join(name.split())


async def process_audio(audio_path: Path, cover_path: Path) -> tuple[str, Path]:
    """
    Async wrapper that offloads the blocking metadata work to a thread-pool,
    keeping the bot's event loop responsive.
    """
    return await asyncio.to_thread(_process_tags, audio_path, cover_path)
