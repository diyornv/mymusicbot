# 🎵 @BASS_MIDAS — Telegram Channel Audio Bot

An automated Telegram bot that intercepts audio files posted in a channel,
rewrites their ID3 metadata (title + cover art), re-uploads the branded version,
and deletes the original post — keeping your channel feed clean and on-brand.

## Features

- **Auto-tagging** — Prepends `@BASS_MIDAS` to every track title.
- **Cover Art Injection** — Replaces album art with your custom channel cover.
- **File Renaming** — Renames the `.mp3` to `{Title} - @BASS_MIDAS.mp3`.
- **Original Cleanup** — Deletes the original message after re-uploading.
- **Non-blocking I/O** — Heavy file work runs in a thread pool so the bot stays responsive.
- **Graceful Errors** — Failures are logged without crashing the bot.

---

## Quick Start

### 1. Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| pip | latest |

### 2. Clone & Install

```bash
cd tgbotmusic
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description | Example |
|---|---|---|
| `BOT_TOKEN` | Token from [@BotFather](https://t.me/BotFather) | `123456:ABC-DEF...` |
| `CHANNEL_ID` | Numeric channel ID (negative) | `-1001234567890` |
| `COVER_IMAGE_PATH` | Relative path to cover image | `assets/channel_cover.jpg` |

> **How to find your channel ID:** Forward any message from the channel to
> [@userinfobot](https://t.me/userinfobot) — it will reply with the numeric ID.

### 4. Add Your Cover Art

Place your branded cover image at `assets/channel_cover.jpg` (or update
`COVER_IMAGE_PATH` in `.env` to point elsewhere).

Supported formats: `.jpg`, `.jpeg`, `.png`, `.webp`.

### 5. Bot Permissions

The bot **must be added as an admin** in the channel with these permissions:

- ✅ Post Messages
- ✅ Delete Messages
- ✅ Edit Messages (optional but recommended)

### 6. Run

```bash
python bot.py
```

---

## Project Structure

```
tgbotmusic/
├── assets/
│   └── channel_cover.jpg   # Your branded cover image
├── bot.py                  # Main entry point & message handler
├── config.py               # Environment loading & validation
├── metadata.py             # Mutagen-based ID3 tag manipulation
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## How It Works

```
Audio posted in channel
        │
        ▼
  bot.py handler
        │
   ┌────┴────┐
   │ Download │  → tmp/{file_id}/filename.mp3
   └────┬────┘
        │
   ┌────┴──────────┐
   │ metadata.py   │
   │  • Read title │
   │  • Rewrite    │
   │    TIT2 tag   │
   │  • Strip old  │
   │    APIC       │
   │  • Embed new  │
   │    cover      │
   │  • Rename     │
   │    file       │
   └────┬──────────┘
        │
   ┌────┴───────┐
   │ Re-upload  │  → send_audio to channel
   └────┬───────┘
        │
   ┌────┴────────────┐
   │ Delete original │
   │ Clean temp dir  │
   └─────────────────┘
```

---

## License

MIT
