import os
import io
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from downloader import VideoDownloader, COOKIES_PATH
from database import db

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "52428800"))
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "300"))
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

downloader = VideoDownloader(timeout=DOWNLOAD_TIMEOUT)

user_data = {}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def format_size(size_bytes: int) -> str:
    if not size_bytes:
        return "Unknown"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_duration(seconds: int) -> str:
    if not seconds:
        return ""
    h, remainder = divmod(int(seconds), 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}:{s:02d}"


def format_number(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def progress_bar(percent: float, length: int = 12) -> str:
    filled = int(length * percent / 100)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent:.0f}%"


SITES_TEXT = (
    "  YouTube, TikTok, Instagram, Twitter/X\n"
    "  Facebook, Reddit, Vimeo, Dailymotion\n"
    "  Twitch, SoundCloud, Pinterest\n"
    "  And 1000+ more sites via yt-dlp"
)


# ─── USER HANDLERS ───


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username or "", user.first_name or "", user.last_name or "")

    if db.is_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return

    text = (
        "┌─────────────────────────────┐\n"
        "│    🎬  <b>VIDEO DOWNLOADER</b>  🎬    │\n"
        "└─────────────────────────────┘\n\n"
        "  ✨ <b>Fast • Free • High Quality</b> ✨\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"  👤 Welcome, <b>{user.first_name}</b>!\n\n"
        "  📩 Send me any video link and I'll\n"
        "  fetch all available qualities\n"
        "  for you to choose from.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"  🌐 <b>Supported Sites:</b>\n{SITES_TEXT}\n\n"
        "  ⚡ <b>Speed:</b> Multi-threaded\n"
        "  🎯 <b>Quality:</b> Up to 4K\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "  💡 <b>Tip:</b> Just paste any link!"
    )

    buttons = []
    if is_admin(user.id):
        buttons.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_menu")])
    buttons.append([InlineKeyboardButton("📊 My Stats", callback_data=f"stats_{user.id}")])
    buttons.append([InlineKeyboardButton("❓ Help", callback_data="help_msg")])

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cookies_status = "✅ Uploaded" if os.path.exists(COOKIES_PATH) else "❌ Not uploaded"
    text = (
        "┌─────────────────────────────┐\n"
        "│       ❓  <b>HOW TO USE</b>       │\n"
        "└─────────────────────────────┘\n\n"
        "  <b>Step 1:</b> Copy a video URL\n"
        "  <b>Step 2:</b> Paste it here\n"
        "  <b>Step 3:</b> Pick quality\n"
        "  <b>Step 4:</b> Wait for download\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"  🍪 <b>Cookies:</b> {cookies_status}\n\n"
        "  📌 <b>Supported sites:</b>\n"
        f"  {SITES_TEXT}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "  🍪 <b>For age-restricted sites</b>\n"
        "  (Pornhub, etc.), send /cookies\n"
        "  with a Netscape cookies.txt file.\n\n"
        "  🚀 <b>Powered by yt-dlp</b>"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)


async def cookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("🚫 Only admin can upload cookies.")
        return

    await update.message.reply_text(
        "┌─────────────────────────────┐\n"
        "│    🍪  <b>UPLOAD COOKIES</b>      │\n"
        "└─────────────────────────────┘\n\n"
        "  Send a <b>Netscape cookies.txt</b>\n"
        "  file to enable bot detection\n"
        "  bypass.\n\n"
        "  <b>How to get cookies.txt:</b>\n"
        "  1. Install the browser extension\n"
        '     "Get cookies.txt LOCALLY"\n'
        "  2. Visit the site while logged in\n"
        "  3. Click the extension → Export\n"
        "  4. Send the .txt file here\n\n"
        "  You can upload multiple files\n"
        "  (YouTube, Pornhub, etc.)\n\n"
        "  ⚠️ Send /skip to cancel.",
        parse_mode=ParseMode.HTML
    )
    context.user_data["awaiting_cookies"] = True


async def handle_cookies_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_cookies"):
        return False

    context.user_data["awaiting_cookies"] = False

    if update.message.text and update.message.text.strip() == "/skip":
        await update.message.reply_text("❌ Cookie upload cancelled.")
        return True

    if not update.message.document:
        await update.message.reply_text("❌ Please send a .txt file.")
        return True

    file = await update.message.document.get_file()
    content = await file.download_as_bytearray()

    try:
        text_content = content.decode("utf-8", errors="ignore")
        if "netscape" in text_content.lower() or "\t" in text_content:
            existing = ""
            if os.path.exists(COOKIES_PATH):
                with open(COOKIES_PATH, "r", encoding="utf-8") as f:
                    existing = f.read()

            domains = set()
            for line in text_content.split("\n"):
                if line.strip() and not line.startswith("#"):
                    parts = line.split("\t")
                    if len(parts) >= 5:
                        domains.add(parts[0].lower())

            merged_lines = []
            for line in existing.split("\n"):
                if line.strip() and not line.startswith("#"):
                    parts = line.split("\t")
                    if len(parts) >= 5 and parts[0].lower() not in domains:
                        merged_lines.append(line)
                else:
                    merged_lines.append(line)

            merged = "\n".join(merged_lines) + "\n" + text_content
            with open(COOKIES_PATH, "w", encoding="utf-8") as f:
                f.write(merged)
            await update.message.reply_text(
                "┌─────────────────────────────┐\n"
                "│    ✅  <b>COOKIES UPLOADED</b>    │\n"
                "└─────────────────────────────┘\n\n"
                f"  🍪 Added cookies for:\n"
                f"  <code>{', '.join(sorted(domains))}</code>\n\n"
                "  Send a video link to test.",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                "❌ Invalid cookies file. Please send a valid Netscape cookies.txt.",
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")

    return True


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = message.from_user
    db.add_user(user.id, user.username or "", user.first_name or "", user.last_name or "")

    if db.is_banned(user.id):
        await message.reply_text("🚫 You are banned from using this bot.")
        return

    url = message.text.strip()

    if not downloader.is_valid_url(url):
        await message.reply_text(
            "┌─────────────────────────────┐\n"
            "│    ❌  <b>INVALID URL</b>         │\n"
            "└─────────────────────────────┘\n\n"
            "  Please send a valid video link.\n\n"
            f"  🌐 <b>Supported sites:</b>\n  {SITES_TEXT}",
            parse_mode=ParseMode.HTML
        )
        return

    loading = await message.reply_text(
        "┌─────────────────────────────┐\n"
        "│    ⏳  <b>FETCHING VIDEO</b>      │\n"
        "└─────────────────────────────┘\n\n"
        f"  {progress_bar(0)}\n\n"
        "  🔍 Analyzing link...\n"
        "  📡 Connecting to source...",
        parse_mode=ParseMode.HTML
    )

    info = downloader.get_video_info(url)
    if not info:
        await loading.edit_text(
            "┌─────────────────────────────┐\n"
            "│    ❌  <b>FETCH FAILED</b>        │\n"
            "└─────────────────────────────┘\n\n"
            "  Could not fetch video info.\n\n"
            "  <b>Possible reasons:</b>\n"
            "  • Video is private or deleted\n"
            "  • Geo-restricted content\n"
            "  • Age-restricted (needs cookies)\n"
            "  • Site blocking server requests\n\n"
            "  💡 <b>For age-restricted sites:</b>\n"
            "  Admin can upload cookies via /cookies",
            parse_mode=ParseMode.HTML
        )
        return

    await loading.edit_text(
        "┌─────────────────────────────┐\n"
        "│    ⏳  <b>FETCHING VIDEO</b>      │\n"
        "└─────────────────────────────┘\n\n"
        f"  {progress_bar(60)}\n\n"
        "  ✅ Video found!\n"
        "  📋 Loading quality options...",
        parse_mode=ParseMode.HTML
    )

    quality_options = downloader.get_quality_options(info["formats"], info.get("duration", 0))
    if not quality_options:
        await loading.edit_text(
            "┌─────────────────────────────┐\n"
            "│    ❌  <b>NO FORMATS</b>          │\n"
            "└─────────────────────────────┘\n\n"
            "  No downloadable formats found.\n"
            "  💡 The video may be protected.",
            parse_mode=ParseMode.HTML
        )
        return

    user_data[message.chat_id] = {
        "url": url,
        "title": info["title"],
        "options": quality_options,
        "thumbnail": info.get("thumbnail", ""),
        "duration": info.get("duration", 0),
        "uploader": info.get("uploader", "Unknown"),
        "view_count": info.get("view_count", 0),
    }

    title = info["title"][:50]
    duration = format_duration(info.get("duration", 0))
    views = format_number(info.get("view_count", 0))
    uploader = info.get("uploader", "Unknown")[:25]

    buttons = []
    quality_lines = []
    for i, opt in enumerate(quality_options):
        size_str = format_size(opt.get("filesize", 0))
        emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"][i] if i < 8 else "⬇️"
        label = f"{emoji} {opt['label']}  •  ~{size_str}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"dl_{opt['format_id']}")])
        quality_lines.append(f"  {opt['label']}  ~  {size_str}")

    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{message.chat_id}")])

    q_list = " | ".join(quality_lines)

    text = (
        f"🎬 <b>{title}</b>\n"
        f"👤 {uploader}  •  ⏱ {duration}  •  👁 {views}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 {q_list}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 Pick a quality:"
    )

    await loading.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_quality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    if not data.startswith("dl_"):
        return

    format_id = data[3:]

    if chat_id not in user_data:
        await query.edit_message_text(
            "┌─────────────────────────────┐\n"
            "│    ⏰  <b>SESSION EXPIRED</b>     │\n"
            "└─────────────────────────────┘\n\n"
            "  Please send the video link again.",
            parse_mode=ParseMode.HTML
        )
        return

    video_info = user_data[chat_id]
    url = video_info["url"]
    title = video_info["title"]

    selected_option = None
    for opt in video_info["options"]:
        if opt["format_id"] == format_id:
            selected_option = opt
            break

    quality_label = selected_option["label"] if selected_option else "best"

    await query.edit_message_text(
        "┌─────────────────────────────┐\n"
        "│    ⬇️  <b>DOWNLOADING</b>          │\n"
        "└─────────────────────────────┘\n\n"
        f"  📌 <b>{title[:50]}</b>\n"
        f"  🎯 Quality: <b>{quality_label}</b>\n\n"
        f"  {progress_bar(0)}\n\n"
        "  ⚡ Multi-threaded download active\n"
        "  🔄 Fetching video fragments...",
        parse_mode=ParseMode.HTML
    )

    start_time = time.time()
    video_stream = downloader.download_video(url, format_id)
    elapsed = time.time() - start_time

    if not video_stream:
        db.log_download(chat_id, title, url, quality_label, 0, elapsed, "failed")
        await query.message.reply_text(
            "┌─────────────────────────────┐\n"
            "│    ❌  <b>DOWNLOAD FAILED</b>     │\n"
            "└─────────────────────────────┘\n\n"
            "  Please try again or select\n"
            "  a different quality.\n\n"
            "  💡 Lower quality = faster download.",
            parse_mode=ParseMode.HTML
        )
        if chat_id in user_data:
            del user_data[chat_id]
        return

    file_size = video_stream.getbuffer().nbytes
    db.log_download(chat_id, title, url, quality_label, file_size, elapsed)

    try:
        if file_size <= MAX_FILE_SIZE:
            video_stream.seek(0)
            await context.bot.send_video(
                chat_id=chat_id,
                video=video_stream,
                caption=(
                    f"🎬 <b>{title[:100]}</b>\n\n"
                    f"🎯 {quality_label} • 📦 {format_size(file_size)} • ⏱ {elapsed:.1f}s"
                ),
                parse_mode=ParseMode.HTML,
                read_timeout=DOWNLOAD_TIMEOUT,
                write_timeout=DOWNLOAD_TIMEOUT
            )
        else:
            video_stream.seek(0)
            await context.bot.send_document(
                chat_id=chat_id,
                document=video_stream,
                caption=(
                    f"🎬 <b>{title[:100]}</b>\n\n"
                    f"🎯 {quality_label} • 📦 {format_size(file_size)} • ⏱ {elapsed:.1f}s"
                ),
                parse_mode=ParseMode.HTML,
                read_timeout=DOWNLOAD_TIMEOUT,
                write_timeout=DOWNLOAD_TIMEOUT
            )
    except Exception as e:
        await query.message.reply_text(
            f"❌ Failed to send video: {str(e)[:100]}"
        )
    finally:
        video_stream.close()
        if chat_id in user_data:
            del user_data[chat_id]


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split("_")[1])
    stats = db.get_user_stats(user_id)

    if not stats:
        await query.edit_message_text("❌ No stats found.")
        return

    text = (
        "┌─────────────────────────────┐\n"
        "│    📊  <b>YOUR STATISTICS</b>     │\n"
        "└─────────────────────────────┘\n\n"
        f"  👤 <b>{stats['first_name'] or 'User'}</b>\n"
        f"  🆔 ID: <code>{stats['user_id']}</code>\n"
        f"  📅 Member since: <b>{stats['first_seen'][:10]}</b>\n"
        f"  ⏰ Last active: <b>{stats['last_active'][:16]}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"  📥 Total Downloads: <b>{stats['total_downloads']}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)


async def handle_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass


# ─── ADMIN HANDLERS ───


async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("🚫 Admin access required.")
        return

    total_users = db.get_total_users()
    total_downloads = db.get_total_downloads()
    today_downloads = db.get_today_downloads()

    text = (
        "┌─────────────────────────────┐\n"
        "│    ⚙️  <b>ADMIN PANEL</b>         │\n"
        "└─────────────────────────────┘\n\n"
        "  📊 <b>Quick Stats:</b>\n"
        f"  👥 Total Users: <b>{total_users}</b>\n"
        f"  📥 Total Downloads: <b>{total_downloads}</b>\n"
        f"  📅 Today's Downloads: <b>{today_downloads}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "  🛠 <b>Management:</b>"
    )

    buttons = [
        [InlineKeyboardButton("👥 All Users", callback_data="admin_users")],
        [InlineKeyboardButton("📈 Daily Stats (7 days)", callback_data="admin_daily")],
        [InlineKeyboardButton("🏆 Top Users", callback_data="admin_top")],
        [InlineKeyboardButton("🔍 Search User", callback_data="admin_search")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    users = db.get_all_users()
    text = (
        "┌─────────────────────────────┐\n"
        "│    👥  <b>ALL USERS</b>           │\n"
        "└─────────────────────────────┘\n\n"
    )

    for u in users[:15]:
        status = "🚫" if u["is_banned"] else "✅"
        name = u["first_name"] or u["username"] or "Unknown"
        text += f"  {status} <b>{name[:20]}</b> • 📥 {u['total_downloads']}\n"
        text += f"     <code>{u['user_id']}</code>\n\n"

    if len(users) > 15:
        text += f"  ... and {len(users) - 15} more users\n"

    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    buttons = [
        [InlineKeyboardButton("🔙 Back", callback_data="admin_menu")]
    ]

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def admin_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    data = db.get_downloads_by_date(7)
    text = (
        "┌─────────────────────────────┐\n"
        "│    📈  <b>DAILY DOWNLOADS</b>      │\n"
        "└─────────────────────────────┘\n\n"
    )

    max_count = max((d["count"] for d in data), default=1) or 1
    for d in data:
        bar_len = int(20 * d["count"] / max_count) if max_count > 0 else 0
        bar = "█" * bar_len + "░" * (20 - bar_len)
        day_name = d["date"][5:]
        text += f"  📅 {day_name}\n"
        text += f"     [{bar}] <b>{d['count']}</b>\n\n"

    total = sum(d["count"] for d in data)
    text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"  📊 7-Day Total: <b>{total}</b>"

    buttons = [[InlineKeyboardButton("🔙 Back", callback_data="admin_menu")]]
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def admin_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    top_users = db.get_top_users(10)
    text = (
        "┌─────────────────────────────┐\n"
        "│    🏆  <b>TOP USERS</b>           │\n"
        "└─────────────────────────────┘\n\n"
    )

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, u in enumerate(top_users):
        name = u["first_name"] or u["username"] or "Unknown"
        medal = medals[i] if i < len(medals) else f"{i+1}."
        text += f"  {medal} <b>{name[:25]}</b>\n"
        text += f"     📥 {u['total_downloads']} downloads\n\n"

    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    buttons = [[InlineKeyboardButton("🔙 Back", callback_data="admin_menu")]]
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def admin_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    await query.edit_message_text(
        "┌─────────────────────────────┐\n"
        "│    🔍  <b>SEARCH USER</b>         │\n"
        "└─────────────────────────────┘\n\n"
        "  Send a user ID to view their\n"
        "  download history.\n\n"
        "  💡 Example: <code>123456789</code>",
        parse_mode=ParseMode.HTML
    )

    context.user_data["awaiting_search_id"] = True


async def admin_handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_search_id"):
        return False

    if not is_admin(update.effective_user.id):
        return False

    context.user_data["awaiting_search_id"] = False

    try:
        user_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Send a numeric ID.")
        return True

    stats = db.get_user_stats(user_id)
    if not stats:
        await update.message.reply_text(f"❌ User {user_id} not found.")
        return True

    downloads = db.get_user_downloads(user_id, limit=10)
    status = "🚫 Banned" if stats["is_banned"] else "✅ Active"

    text = (
        "┌─────────────────────────────┐\n"
        "│    👤  <b>USER PROFILE</b>        │\n"
        "└─────────────────────────────┘\n\n"
        f"  🆔 ID: <code>{stats['user_id']}</code>\n"
        f"  👤 Name: <b>{stats['first_name'] or 'N/A'}</b>\n"
        f"  📛 Username: @{stats['username'] or 'N/A'}\n"
        f"  📊 Status: {status}\n"
        f"  📥 Downloads: <b>{stats['total_downloads']}</b>\n"
        f"  📅 First seen: <b>{stats['first_seen'][:10]}</b>\n"
        f"  ⏰ Last active: <b>{stats['last_active'][:16]}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "  📜 <b>Recent Downloads:</b>\n\n"
    )

    for d in downloads:
        title = d["video_title"][:35]
        text += f"  🎬 {title}\n"
        text += f"     🎯 {d['quality']} • 📦 {format_size(d['file_size'])}\n"
        text += f"     📅 {d['timestamp'][:16]}\n\n"

    if not downloads:
        text += "  (No downloads yet)\n\n"

    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    buttons = []
    if stats["is_banned"]:
        buttons.append([InlineKeyboardButton(f"✅ Unban User {user_id}", callback_data=f"unban_{user_id}")])
    else:
        buttons.append([InlineKeyboardButton(f"🚫 Ban User {user_id}", callback_data=f"ban_{user_id}")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="admin_menu")])

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return True


async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    user_id = int(query.data.split("_")[1])
    db.ban_user(user_id)
    await query.edit_message_text(
        f"✅ User <code>{user_id}</code> has been <b>banned</b>.",
        parse_mode=ParseMode.HTML
    )


async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    user_id = int(query.data.split("_")[1])
    db.unban_user(user_id)
    await query.edit_message_text(
        f"✅ User <code>{user_id}</code> has been <b>unbanned</b>.",
        parse_mode=ParseMode.HTML
    )


async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    total_users = db.get_total_users()
    total_downloads = db.get_total_downloads()
    today_downloads = db.get_today_downloads()

    text = (
        "┌─────────────────────────────┐\n"
        "│    ⚙️  <b>ADMIN PANEL</b>         │\n"
        "└─────────────────────────────┘\n\n"
        "  📊 <b>Quick Stats:</b>\n"
        f"  👥 Total Users: <b>{total_users}</b>\n"
        f"  📥 Total Downloads: <b>{total_downloads}</b>\n"
        f"  📅 Today's Downloads: <b>{today_downloads}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "  🛠 <b>Management:</b>"
    )

    buttons = [
        [InlineKeyboardButton("👥 All Users", callback_data="admin_users")],
        [InlineKeyboardButton("📈 Daily Stats (7 days)", callback_data="admin_daily")],
        [InlineKeyboardButton("🏆 Top Users", callback_data="admin_top")],
        [InlineKeyboardButton("🔍 Search User", callback_data="admin_search")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="admin_back_main")],
    ]

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def admin_back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    text = (
        "┌─────────────────────────────┐\n"
        "│    🎬  <b>VIDEO DOWNLOADER</b>  🎬    │\n"
        "└─────────────────────────────┘\n\n"
        "  ✨ <b>Fast • Free • High Quality</b> ✨\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"  👤 Welcome, <b>{user.first_name}</b>!\n\n"
        "  📩 Send me any video link and I'll\n"
        "  fetch all available qualities\n"
        "  for you to choose from.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"  🌐 <b>Supported Sites:</b>\n{SITES_TEXT}\n\n"
        "  ⚡ <b>Speed:</b> Multi-threaded\n"
        "  🎯 <b>Quality:</b> Up to 4K\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    buttons = []
    if is_admin(user.id):
        buttons.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_menu")])
    buttons.append([InlineKeyboardButton("📊 My Stats", callback_data=f"stats_{user.id}")])
    buttons.append([InlineKeyboardButton("❓ Help", callback_data="help_msg")])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )
