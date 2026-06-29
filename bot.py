import os
import sys
import asyncio
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

import database as db
import downloader

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
COOKIES_FILE = os.getenv("COOKIES_FILE")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()

URL_PATTERN = r'https?://[^\s<>"{}|\\^`\[\]]+'


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def _format_size(size: int | None) -> str:
    if not size:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _platform_emoji(platform: str) -> str:
    return {
        "youtube": "YouTube",
        "spotify": "Spotify",
        "instagram": "Instagram",
        "soundcloud": "SoundCloud",
        "pinterest": "Pinterest",
    }.get(platform, "Unknown")


async def _send_file(message: Message, filepath: str, caption: str):
    try:
        file = FSInputFile(filepath)
        ext = os.path.splitext(filepath)[1].lower()

        if ext in (".mp3", ".m4a", ".opus", ".wav", ".flac", ".ogg"):
            await message.answer_audio(file, caption=caption)
        elif ext in (".mp4", ".mkv", ".webm"):
            await message.answer_video(file, caption=caption)
        else:
            await message.answer_document(file, caption=caption)
    except Exception as e:
        await message.answer(f"Failed to send file: {e}")
    finally:
        _cleanup(filepath)


def _cleanup(filepath: str):
    try:
        if os.path.isfile(filepath):
            os.remove(filepath)
        directory = os.path.dirname(filepath)
        if directory and os.path.isdir(directory) and not os.listdir(directory):
            os.rmdir(directory)
    except Exception:
        pass


@router.message(CommandStart())
async def cmd_start(message: Message):
    db.increment_downloads(message.from_user.id, message.from_user.username or "")
    text = (
        "<b>Media Downloader Bot</b>\n\n"
        "Send me a link and I'll download it for you.\n\n"
        "<b>Supported platforms:</b>\n"
        "YouTube\n"
        "Spotify\n"
        "Instagram\n"
        "SoundCloud\n"
        "Pinterest\n\n"
        "Just paste a URL and send!"
    )
    await message.answer(text)


@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "<b>How to use:</b>\n\n"
        "1. Copy a link from a supported platform\n"
        "2. Paste it here and send\n"
        "3. Wait for the download\n\n"
        "<b>Commands:</b>\n"
        "/start - Show welcome message\n"
        "/stats - Your download count\n"
        "/help - This message"
    )
    await message.answer(text)


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    count = db.get_stats(message.from_user.id)
    total = db.get_total_stats()
    await message.answer(
        f"<b>Your downloads:</b> {count}\n<b>Total bot downloads:</b> {total}"
    )


@router.message(F.text)
async def handle_message(message: Message):
    text = message.text.strip()
    if not text or not text.startswith("http"):
        await message.answer("Send me a valid URL to download.")
        return

    platform = downloader.detect_platform(text)
    if platform == "unknown":
        await message.answer(
            "Unsupported platform. Send a link from:\n"
            "YouTube, Spotify, Instagram, SoundCloud, or Pinterest."
        )
        return

    status = await message.answer(f"Fetching info from {_platform_emoji(platform)}...")

    try:
        info = downloader.get_info(text, COOKIES_FILE)
    except Exception as e:
        await status.edit_text(f"Failed to fetch info: {e}")
        return

    duration = _format_duration(info.get("duration"))
    size = _format_size(info.get("filesize"))
    meta = f"<b>{info['title']}</b>\nPlatform: {_platform_emoji(info['platform'])}"
    if duration:
        meta += f"\nDuration: {duration}"
    if size:
        meta += f"\nSize: {size}"

    await status.edit_text(meta + "\n\nDownloading...")

    try:
        filepath, ext = downloader.download(text, COOKIES_FILE)
    except Exception as e:
        await status.edit_text(f"Download failed: {e}")
        return

    caption = f"<b>{info['title']}</b>\n{_platform_emoji(info['platform'])}"

    await status.edit_text("Sending file...")
    await _send_file(message, filepath, caption)
    await status.delete()

    db.increment_downloads(message.from_user.id, message.from_user.username or "")


async def main():
    db.init_db()
    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
