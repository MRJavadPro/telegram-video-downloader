import os
import sys
import asyncio
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

import database as db
import downloader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
COOKIES_FILE = os.getenv("COOKIES_FILE")
COOKIES_CONTENT = os.getenv("COOKIES_CONTENT")

if COOKIES_FILE and not os.path.isabs(COOKIES_FILE):
    COOKIES_FILE = os.path.join(os.path.dirname(__file__), COOKIES_FILE)
if COOKIES_FILE and os.path.isfile(COOKIES_FILE):
    logger.info(f"Cookies file found: {COOKIES_FILE}")
elif COOKIES_CONTENT:
    cookies_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    with open(cookies_path, "w") as f:
        f.write(COOKIES_CONTENT)
    COOKIES_FILE = cookies_path
    logger.info(f"Cookies written from env var to: {COOKIES_FILE}")
else:
    logger.warning("No cookies configured")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


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
        elif ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            await message.answer_photo(file, caption=caption)
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
    if db.is_banned(message.from_user.id):
        await message.answer("You are banned from using this bot.")
        return
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
    if db.is_banned(message.from_user.id):
        await message.answer("You are banned from using this bot.")
        return
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
    if db.is_banned(message.from_user.id):
        await message.answer("You are banned from using this bot.")
        return
    count = db.get_stats(message.from_user.id)
    total = db.get_total_stats()
    await message.answer(
        f"<b>Your downloads:</b> {count}\n<b>Total bot downloads:</b> {total}"
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, command: CommandObject):
    if not _is_admin(message.from_user.id):
        return
    total_users = db.get_total_users()
    total_downloads = db.get_total_stats()
    banned = db.get_banned_users()
    text = (
        f"<b>Admin Panel</b>\n\n"
        f"Total users: {total_users}\n"
        f"Total downloads: {total_downloads}\n"
        f"Banned users: {len(banned)}\n\n"
        f"<b>Admin commands:</b>\n"
        f"/users - List all users\n"
        f"/history &lt;user_id&gt; - User download history\n"
        f"/ban &lt;user_id&gt; [reason] - Ban user\n"
        f"/unban &lt;user_id&gt; - Unban user\n"
        f"/banned - List banned users"
    )
    await message.answer(text)


@router.message(Command("users"))
async def cmd_users(message: Message):
    if not _is_admin(message.from_user.id):
        return
    users = db.get_all_users()
    if not users:
        await message.answer("No users yet.")
        return
    lines = ["<b>All Users:</b>\n"]
    for i, u in enumerate(users, 1):
        name = u.get("full_name") or u.get("username") or "Unknown"
        uname = f" @{u['username']}" if u.get("username") else ""
        lines.append(
            f"{i}. <code>{u['user_id']}</code> - {name}{uname}\n"
            f"   Downloads: {u['download_count']}"
        )
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await message.answer(text)


@router.message(Command("history"))
async def cmd_history(message: Message, command: CommandObject):
    if not _is_admin(message.from_user.id):
        return
    args = command.args
    if not args or not args.strip().isdigit():
        await message.answer("Usage: /history &lt;user_id&gt;")
        return
    user_id = int(args.strip())
    history = db.get_user_history(user_id)
    if not history:
        await message.answer(f"No downloads found for user <code>{user_id}</code>.")
        return
    lines = [f"<b>History for {user_id}:</b>\n"]
    for h in history:
        lines.append(
            f"[{_platform_emoji(h['platform'])}] {h['title']}\n"
            f"<code>{h['timestamp']}</code>"
        )
    text = "\n\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await message.answer(text)


@router.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject):
    if not _is_admin(message.from_user.id):
        return
    args = command.args
    if not args:
        await message.answer("Usage: /ban &lt;user_id&gt; [reason]")
        return
    parts = args.split(maxsplit=1)
    user_id_str = parts[0]
    reason = parts[1] if len(parts) > 1 else ""
    if not user_id_str.isdigit():
        await message.answer("User ID must be a number.")
        return
    user_id = int(user_id_str)
    if user_id in ADMIN_IDS:
        await message.answer("Cannot ban an admin.")
        return
    db.ban_user(user_id, message.from_user.id, reason)
    await message.answer(f"User <code>{user_id}</code> has been banned.")


@router.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject):
    if not _is_admin(message.from_user.id):
        return
    args = command.args
    if not args or not args.strip().isdigit():
        await message.answer("Usage: /unban &lt;user_id&gt;")
        return
    user_id = int(args.strip())
    db.unban_user(user_id)
    await message.answer(f"User <code>{user_id}</code> has been unbanned.")


@router.message(Command("banned"))
async def cmd_banned(message: Message):
    if not _is_admin(message.from_user.id):
        return
    banned = db.get_banned_users()
    if not banned:
        await message.answer("No banned users.")
        return
    lines = ["<b>Banned Users:</b>\n"]
    for b in banned:
        name = b.get("full_name") or b.get("username") or "Unknown"
        reason = f" - {b['reason']}" if b.get("reason") else ""
        lines.append(
            f"<code>{b['user_id']}</code> - {name}{reason}\n"
            f"Banned: {b['timestamp']}"
        )
    text = "\n\n".join(lines)
    await message.answer(text)


@router.message(F.text)
async def handle_message(message: Message):
    if db.is_banned(message.from_user.id):
        await message.answer("You are banned from using this bot.")
        return

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

    db.increment_downloads(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or "",
    )
    db.log_download(
        message.from_user.id,
        platform,
        info["title"],
        text,
    )


async def main():
    dp.include_router(router)
    db.init_db()
    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
