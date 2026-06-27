import os
import io
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from downloader import VideoDownloader, COOKIES_PATH, is_spotify_url
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


SITES_TEXT = (
    "YouTube, TikTok, Instagram, Twitter/X\n"
    "Facebook, Reddit, Vimeo, Dailymotion\n"
    "SoundCloud, Twitch, Pinterest\n"
    "Spotify, and 1000+ more sites"
)


# ─── USER HANDLERS ───


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username or "", user.first_name or "", user.last_name or "")

    if db.is_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return

    text = (
        f"🎬 Video Downloader\n\n"
        f"Hey {user.first_name}! 👋\n"
        f"Send me any video or music link\n"
        f"and I'll download it for you.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌐 Supported sites:\n"
        f"{SITES_TEXT}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 Just paste any link to start!"
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
        "❓ How To Use\n\n"
        "Step 1: Copy a video/music URL\n"
        "Step 2: Paste it here\n"
        "Step 3: Pick quality\n"
        "Step 4: Wait for download\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🍪 Cookies: {cookies_status}\n\n"
        f"🌐 Supported sites:\n"
        f"{SITES_TEXT}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "For age-restricted or bot-blocked\n"
        "sites, send /cookies with a\n"
        "Netscape cookies.txt file."
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)


async def cookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("🚫 Only admin can upload cookies.")
        return

    await update.message.reply_text(
        "🍪 Upload Cookies\n\n"
        "Send a Netscape cookies.txt file\n"
        "to bypass bot detection.\n\n"
        "How to get cookies.txt:\n"
        '1. Install "Get cookies.txt LOCALLY"\n'
        "   browser extension\n"
        "2. Visit the site while logged in\n"
        "3. Click the extension → Export\n"
        "4. Send the .txt file here\n\n"
        "You can upload multiple files\n"
        "(YouTube, Pornhub, etc.)\n\n"
        "⚠️ Send /skip to cancel.",
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
                f"✅ Cookies Uploaded\n\n"
                f"Added cookies for:\n"
                f"{', '.join(sorted(domains))}\n\n"
                f"Send a video link to test.",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                "❌ Invalid cookies file. Send a valid Netscape cookies.txt.",
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
            "❌ Invalid URL\n\n"
            "Please send a valid video or music link.\n\n"
            f"🌐 Supported sites:\n{SITES_TEXT}",
            parse_mode=ParseMode.HTML
        )
        return

    loading = await message.reply_text(
        "⏳ Fetching...\n\n"
        "🔍 Analyzing link..."
    )

    if is_spotify_url(url):
        chat_id = message.chat_id
        await loading.edit_text(
            "🎵 Spotify Track\n\n"
            "⬇️ Downloading audio..."
        )

        start_time = time.time()
        audio_stream = downloader.download_spotify(url)
        elapsed = time.time() - start_time

        if not audio_stream:
            await loading.edit_text(
                "❌ Download Failed\n\n"
                "Could not download Spotify track.\n"
                "The link may be invalid or restricted."
            )
            return

        file_size = audio_stream.getbuffer().nbytes
        info = downloader.get_spotify_info(url)
        title = info.get("title", "Spotify Track") if info else "Spotify Track"
        artist = info.get("artist", "Unknown") if info else "Unknown"

        db.log_download(chat_id, f"{artist} - {title}", url, "audio", file_size, elapsed)

        try:
            audio_stream.seek(0)
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio_stream,
                title=title,
                performer=artist,
                caption=f"🎵 {artist} - {title}\n📦 {format_size(file_size)} • ⏱ {elapsed:.1f}s",
                parse_mode=ParseMode.HTML,
                read_timeout=DOWNLOAD_TIMEOUT,
                write_timeout=DOWNLOAD_TIMEOUT
            )
        except Exception as e:
            await loading.edit_text(f"❌ Failed to send: {str(e)[:100]}")
        finally:
            audio_stream.close()
        return

    info = downloader.get_video_info(url)
    if not info:
        await loading.edit_text(
            "❌ Fetch Failed\n\n"
            "Could not fetch video info.\n\n"
            "Possible reasons:\n"
            "• Video is private or deleted\n"
            "• Geo-restricted content\n"
            "• Age-restricted (needs cookies)\n"
            "• Site blocking server requests\n\n"
            "💡 Admin can upload cookies via /cookies"
        )
        return

    quality_options = downloader.get_quality_options(info["formats"], info.get("duration", 0))
    if not quality_options:
        await loading.edit_text(
            "❌ No Formats\n\n"
            "No downloadable formats found.\n"
            "The video may be protected."
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

    title = info["title"][:55]
    duration = format_duration(info.get("duration", 0))
    views = format_number(info.get("view_count", 0))
    uploader = info.get("uploader", "Unknown")[:25]

    buttons = []
    for i, opt in enumerate(quality_options):
        size_str = format_size(opt.get("filesize", 0))
        emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"][i] if i < 8 else "⬇️"
        label = f"{emoji} {opt['label']}  •  ~{size_str}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"dl_{opt['format_id']}")])

    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{message.chat_id}")])

    text = (
        f"🎬 {title}\n"
        f"👤 {uploader} • ⏱ {duration} • 👁 {views}\n\n"
        f"Pick a quality:"
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
            "⏰ Session Expired\n\n"
            "Please send the video link again."
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
        f"⬇️ Downloading\n\n"
        f"📌 {title[:50]}\n"
        f"🎯 Quality: {quality_label}\n\n"
        f"⚡ Multi-threaded download active..."
    )

    start_time = time.time()
    video_stream = downloader.download_video(url, format_id)
    elapsed = time.time() - start_time

    if not video_stream:
        db.log_download(chat_id, title, url, quality_label, 0, elapsed, "failed")
        await query.message.reply_text(
            "❌ Download Failed\n\n"
            "Please try again or select a different quality.\n\n"
            "💡 Lower quality = faster download."
        )
        if chat_id in user_data:
            del user_data[chat_id]
        return

    file_size = video_stream.getbuffer().nbytes
    db.log_download(chat_id, title, url, quality_label, file_size, elapsed)

    caption = (
        f"🎬 {title[:100]}\n\n"
        f"🎯 {quality_label} • 📦 {format_size(file_size)} • ⏱ {elapsed:.1f}s"
    )

    try:
        if file_size <= MAX_FILE_SIZE:
            video_stream.seek(0)
            await context.bot.send_video(
                chat_id=chat_id,
                video=video_stream,
                caption=caption,
                parse_mode=ParseMode.HTML,
                read_timeout=DOWNLOAD_TIMEOUT,
                write_timeout=DOWNLOAD_TIMEOUT
            )
        else:
            video_stream.seek(0)
            await context.bot.send_document(
                chat_id=chat_id,
                document=video_stream,
                caption=caption,
                parse_mode=ParseMode.HTML,
                read_timeout=DOWNLOAD_TIMEOUT,
                write_timeout=DOWNLOAD_TIMEOUT
            )
    except Exception as e:
        await query.message.reply_text(
            f"❌ Failed to send: {str(e)[:100]}"
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
        f"📊 Your Statistics\n\n"
        f"👤 {stats['first_name'] or 'User'}\n"
        f"🆔 {stats['user_id']}\n"
        f"📅 Member since: {stats['first_seen'][:10]}\n"
        f"⏰ Last active: {stats['last_active'][:16]}\n\n"
        f"📥 Total Downloads: {stats['total_downloads']}"
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
        "⚙️ Admin Panel\n\n"
        f"👥 Total Users: {total_users}\n"
        f"📥 Total Downloads: {total_downloads}\n"
        f"📅 Today: {today_downloads}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Management:"
    )

    buttons = [
        [InlineKeyboardButton("👥 All Users", callback_data="admin_users")],
        [InlineKeyboardButton("📈 Daily Stats", callback_data="admin_daily")],
        [InlineKeyboardButton("🏆 Top Users", callback_data="admin_top")],
        [InlineKeyboardButton("🔍 Search User", callback_data="admin_search")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
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
    text = "👥 All Users\n\n"

    for u in users[:15]:
        status = "🚫" if u["is_banned"] else "✅"
        name = u["first_name"] or u["username"] or "Unknown"
        text += f"{status} {name[:20]} • 📥 {u['total_downloads']}\n"
        text += f"  {u['user_id']}\n\n"

    if len(users) > 15:
        text += f"... and {len(users) - 15} more users\n"

    text += "━━━━━━━━━━━━━━━━━━━━━━━"

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
    text = "📈 Daily Downloads\n\n"

    max_count = max((d["count"] for d in data), default=1) or 1
    for d in data:
        bar_len = int(20 * d["count"] / max_count) if max_count > 0 else 0
        bar = "█" * bar_len + "░" * (20 - bar_len)
        day_name = d["date"][5:]
        text += f"📅 {day_name}\n"
        text += f"   [{bar}] {d['count']}\n\n"

    total = sum(d["count"] for d in data)
    text += f"━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📊 7-Day Total: {total}"

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
    text = "🏆 Top Users\n\n"

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, u in enumerate(top_users):
        name = u["first_name"] or u["username"] or "Unknown"
        medal = medals[i] if i < len(medals) else f"{i+1}."
        text += f"{medal} {name[:25]}\n"
        text += f"   📥 {u['total_downloads']} downloads\n\n"

    text += "━━━━━━━━━━━━━━━━━━━━━━━"

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
        "🔍 Search User\n\n"
        "Send a user ID to view their\n"
        "download history.\n\n"
        "💡 Example: 123456789"
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
        f"👤 User Profile\n\n"
        f"🆔 {stats['user_id']}\n"
        f"👤 {stats['first_name'] or 'N/A'}\n"
        f"📛 @{stats['username'] or 'N/A'}\n"
        f"📊 Status: {status}\n"
        f"📥 Downloads: {stats['total_downloads']}\n"
        f"📅 Since: {stats['first_seen'][:10]}\n"
        f"⏰ Active: {stats['last_active'][:16]}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📜 Recent Downloads:\n\n"
    )

    for d in downloads:
        title = d["video_title"][:35]
        text += f"🎬 {title}\n"
        text += f"   🎯 {d['quality']} • 📦 {format_size(d['file_size'])}\n"
        text += f"   📅 {d['timestamp'][:16]}\n\n"

    if not downloads:
        text += "(No downloads yet)\n\n"

    text += "━━━━━━━━━━━━━━━━━━━━━━━"

    buttons = []
    if stats["is_banned"]:
        buttons.append([InlineKeyboardButton(f"✅ Unban {user_id}", callback_data=f"unban_{user_id}")])
    else:
        buttons.append([InlineKeyboardButton(f"🚫 Ban {user_id}", callback_data=f"ban_{user_id}")])
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
    await query.edit_message_text(f"✅ User {user_id} has been banned.")


async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    user_id = int(query.data.split("_")[1])
    db.unban_user(user_id)
    await query.edit_message_text(f"✅ User {user_id} has been unbanned.")


async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    total_users = db.get_total_users()
    total_downloads = db.get_total_downloads()
    today_downloads = db.get_today_downloads()

    text = (
        "⚙️ Admin Panel\n\n"
        f"👥 Total Users: {total_users}\n"
        f"📥 Total Downloads: {total_downloads}\n"
        f"📅 Today: {today_downloads}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Management:"
    )

    buttons = [
        [InlineKeyboardButton("👥 All Users", callback_data="admin_users")],
        [InlineKeyboardButton("📈 Daily Stats", callback_data="admin_daily")],
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
        f"🎬 Video Downloader\n\n"
        f"Hey {user.first_name}! 👋\n"
        f"Send me any video or music link\n"
        f"and I'll download it for you.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌐 Supported sites:\n"
        f"{SITES_TEXT}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 Just paste any link to start!"
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
