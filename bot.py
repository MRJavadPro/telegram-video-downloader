import os
import sys
import platform

if platform.system() == "Windows":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from dotenv import load_dotenv
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)

from handlers import (
    start,
    handle_message,
    handle_quality_selection,
    handle_stats,
    handle_error,
    help_callback,
    cookies_command,
    handle_cookies_file,
    admin_menu,
    admin_users,
    admin_daily,
    admin_top,
    admin_search,
    admin_handle_search,
    admin_ban,
    admin_unban,
    admin_back,
    admin_back_main,
)

load_dotenv()


async def route_text(update, context):
    if await admin_handle_search(update, context):
        return
    if await handle_cookies_file(update, context):
        return
    await handle_message(update, context)


async def route_document(update, context):
    if await handle_cookies_file(update, context):
        return

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN not set. Create a .env file with your token.")
    sys.exit(1)


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("cookies", cookies_command))
    app.add_handler(MessageHandler(filters.Document.ALL, route_document))

    app.add_handler(CallbackQueryHandler(help_callback, pattern=r"^help_msg$"))
    app.add_handler(CallbackQueryHandler(handle_stats, pattern=r"^stats_"))
    app.add_handler(CallbackQueryHandler(admin_menu, pattern=r"^admin_menu$"))
    app.add_handler(CallbackQueryHandler(admin_users, pattern=r"^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_daily, pattern=r"^admin_daily$"))
    app.add_handler(CallbackQueryHandler(admin_top, pattern=r"^admin_top$"))
    app.add_handler(CallbackQueryHandler(admin_search, pattern=r"^admin_search$"))
    app.add_handler(CallbackQueryHandler(admin_ban, pattern=r"^ban_"))
    app.add_handler(CallbackQueryHandler(admin_unban, pattern=r"^unban_"))
    app.add_handler(CallbackQueryHandler(admin_back, pattern=r"^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_back_main, pattern=r"^admin_back_main$"))
    app.add_handler(CallbackQueryHandler(handle_quality_selection, pattern=r"^dl_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, route_text))

    app.add_error_handler(handle_error)

    print("🤖 Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
