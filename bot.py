import os
import json
import logging
import re
import asyncio
import sys
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ChatMemberHandler
from deep_translator import GoogleTranslator
from langdetect import detect
from db import Database

# Fix for Windows Python 3.12+ event loop issue
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Default configuration
config = {
    "bot_token": "YOUR_TELEGRAM_BOT_TOKEN_HERE",
    "admin_chat_id": "",
    "free_daily_limit": 50,
    "pricing": {
        "premium_monthly_usd": 10.0,
        "pay_per_use_usd": 0.001
    }
}

# Load from config.json if it exists
if os.path.exists("config.json"):
    try:
        with open("config.json", "r") as f:
            user_config = json.load(f)
            if isinstance(user_config, dict):
                # Update top-level keys
                for key in ["bot_token", "admin_chat_id", "free_daily_limit"]:
                    if key in user_config:
                        config[key] = user_config[key]
                # Update pricing if it exists
                if "pricing" in user_config and isinstance(user_config["pricing"], dict):
                    for p_key in ["premium_monthly_usd", "pay_per_use_usd"]:
                        if p_key in user_config["pricing"]:
                            config["pricing"][p_key] = user_config["pricing"][p_key]
    except Exception as e:
        logger.error(f"Error loading config.json: {e}")

# Environment Variables override (for Heroku)
config["bot_token"] = os.getenv("BOT_TOKEN", config["bot_token"])
config["admin_chat_id"] = os.getenv("ADMIN_CHAT_ID", config["admin_chat_id"])

env_limit = os.getenv("FREE_DAILY_LIMIT")
if env_limit:
    config["free_daily_limit"] = int(env_limit)

env_premium = os.getenv("PREMIUM_MONTHLY_USD")
if env_premium:
    config["pricing"]["premium_monthly_usd"] = float(env_premium)

env_pay = os.getenv("PAY_PER_USE_USD")
if env_pay:
    config["pricing"]["pay_per_use_usd"] = float(env_pay)

db = Database()


def detect_language(text):
    """Detect language using Google Translate API directly for better accuracy (supports Yoruba)."""
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": text[:500]}
        resp = requests.get(url, params=params, timeout=5)
        # the response structure is typically [[[...]], null, 'yo', ...]
        return resp.json()[2]
    except Exception as e:
        logger.error(f"Google detect error, falling back to langdetect: {e}")
        try:
            return detect(text)
        except:
            return 'en' # safe fallback

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *Welcome to the AI Translator Bot!*\n\n"
        "I break language barriers in group chats.\n\n"
        "🌍 *How it works:*\n"
        "• Any message not in the group's language → I translate it to the group language\n"
        "• If you reply to a foreign speaker → I translate your reply into their language\n"
        "• If they reply back → I translate it back to the group language\n\n"
        "🛠️ *Please make me an Admin in your group for best results!*\n\n"
        "📚 *Commands:*\n"
        "🔹 /setlang [code] - Set group default language (Admins only, default: `en`)\n"
        "🔹 /mylanguage [code] - Set your personal preferred language\n"
        "🔹 /langcodes - View common language codes\n"
        "🔹 /languages - View ALL supported language codes\n"
        "🔹 /balance - Check your stats\n"
        "🔹 /premium - View premium plans\n"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


async def greet_new_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greets the group when the bot is added."""
    result = update.my_chat_member
    if not result:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status

    if old_status not in ["member", "administrator"] and new_status in ["member", "administrator"]:
        msg = (
            "🚀 *Hello everyone! I am your AI Translation Assistant!* 🚀\n\n"
            "My job is to make sure language is never a barrier here. 🌍\n"
            "By default, any message NOT in *English* will be automatically translated.\n\n"
            "🔄 *How I work:*\n"
            "• Foreign message sent → I translate it to English for everyone\n"
            "• You reply in English to a foreign speaker → I translate your reply to their language\n"
            "• They reply back → I translate it back to English\n\n"
            "⚙️ *Setup:*\n"
            "👉 *Make Me Admin* and use `/setlang <code>` to set group language\n"
            "   e.g. `/setlang en` for English, `/setlang es` for Spanish, `/setlang fr` for French\n"
            "👉 Type `/langcodes` to see all common codes, or `/languages` for the full list!\n\n"
            "Users can also set personal language with `/mylanguage <code>` 💬\n"
            "Let's start chatting! 🎉"
        )
        try:
            await context.bot.send_message(chat_id=result.chat.id, text=msg, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to send intro message: {e}")


async def langcodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🌐 *Common Language Codes:*\n\n"
        "🇬🇧 English: `en`\n"
        "🇪🇸 Spanish: `es`\n"
        "🇫🇷 French: `fr`\n"
        "🇨🇳 Chinese (Simplified): `zh-CN`\n"
        "🇩🇪 German: `de`\n"
        "🇮🇹 Italian: `it`\n"
        "🇯🇵 Japanese: `ja`\n"
        "🇰🇷 Korean: `ko`\n"
        "🇷🇺 Russian: `ru`\n"
        "🇵🇹 Portuguese: `pt`\n"
        "🇦🇪 Arabic: `ar`\n"
        "🇮🇳 Hindi: `hi`\n"
        "🇹🇷 Turkish: `tr`\n"
        "🇳🇱 Dutch: `nl`\n"
        "🇵🇱 Polish: `pl`\n"
        "🇸🇦 Hebrew: `iw`\n"
        "🇹🇭 Thai: `th`\n"
        "🇻🇳 Vietnamese: `vi`\n"
        "🇬🇷 Greek: `el`\n"
        "🇸🇪 Swedish: `sv`\n"
        "🇳🇬 Yoruba: `yo`\n\n"
        "_Use these codes with /mylanguage or /setlang_"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


async def languages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows ALL supported languages chunked into multiple messages."""
    langs = GoogleTranslator().get_supported_languages(as_dict=True)
    sorted_langs = sorted(langs.items())
    chunks = []
    current_chunk = "📋 *Full List of Supported Languages:*\n\n"

    for name, code in sorted_langs:
        line = f"• {name.title()}: `{code}`\n"
        if len(current_chunk) + len(line) > 4000:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += line
    chunks.append(current_chunk)

    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode='Markdown')


async def mylanguage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /mylanguage [language_code]\nExample: /mylanguage es\n\nType /langcodes to see codes."
        )
        return
    lang = context.args[0].lower()
    user_id = update.effective_user.id
    username = update.effective_user.username
    db.set_user_lang(user_id, lang, username)
    await update.message.reply_text(f"✅ Your preferred language is now set to: `{lang}`", parse_mode='Markdown')


async def setlang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == 'private':
        await update.message.reply_text("This command is only available in groups.")
        return

    user_id = update.effective_user.id
    member = await chat.get_member(user_id)
    if member.status not in ['creator', 'administrator']:
        await update.message.reply_text("⛔ Only group administrators can change the group's default language.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /setlang [language_code]\nExample: /setlang en\n\nType /langcodes to see codes.")
        return

    lang = context.args[0].lower()
    db.set_group_lang(chat.id, lang)
    await update.message.reply_text(f"✅ The group's default language is now set to: `{lang}`", parse_mode='Markdown')


async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💎 *Premium Plans*\n\n"
        f"🌟 *Monthly Premium*: ${config['pricing']['premium_monthly_usd']} / month\n"
        "   Unlimited translations, no daily limit!\n"
        f"⚡ *Pay-per-use*: ${config['pricing']['pay_per_use_usd']} per translation\n\n"
        "*(Payments will be integrated via Telegram BotFather soon!)*"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only allow the designated admin to use this command
    if str(update.effective_chat.id) != config.get("admin_chat_id"):
        return

    users_count, groups_count, premium_count = db.get_stats()
    msg = (
        "📊 *Bot Statistics* 📊\n\n"
        f"👤 *Total Users*: {users_count}\n"
        f"👥 *Total Groups*: {groups_count}\n"
        f"🌟 *Premium Users*: {premium_count}\n\n"
        "_(Only visible to you)_"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal, is_prem, expiry = db.get_user_balance(user_id)
    prem_text = f"Yes (Expires: {expiry})" if is_prem else "No"
    msg = (
        f"💰 *Your Balance*: ${bal:.4f}\n"
        f"💎 *Premium Status*: {prem_text}"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


async def translate_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text or msg.text.startswith('/'):
        return

    chat_id = msg.chat_id
    user_id = msg.from_user.id
    username = msg.from_user.username or msg.from_user.first_name

    # Rate limiting
    if msg.chat.type != 'private':
        allowed = db.check_and_increment_group_limit(chat_id, config['free_daily_limit'])
        if not allowed:
            if not db.is_premium(user_id):
                if not db.deduct_balance(user_id, config['pricing']['pay_per_use_usd']):
                    return

    group_lang = db.get_group_lang(chat_id)
    text = msg.text
    clean_text = text.strip()

    if len(clean_text) < 2:
        return

    # Detect sender's language (using Google-based detection for Yoruba support)
    src_lang = detect_language(clean_text)
    
    logger.info(f"[{username}] src_lang={src_lang}, group_lang={group_lang}, text={clean_text[:40]}")

    # Track user language automatically ONLY if they haven't explicitly set one via /mylanguage
    if len(clean_text) > 4:
        existing_lang = db.get_user_lang(user_id)
        # Avoid overwriting a manual setting with a mis-detection, especially if it matches the group lang 
        # (meaning they are speaking the group's native language right now)
        if not existing_lang or (src_lang != group_lang):
            db.set_user_lang(user_id, src_lang, msg.from_user.username)

    # ─── CASE 1: Replying to someone ────────────────────────────────────────
    reply_to = msg.reply_to_message
    if reply_to:
        replied_user = reply_to.from_user
        if not replied_user:
            return

        target_lang = None
        target_display = None  # The person we're translating FOR

        if replied_user.is_bot:
            # Bot sent something like "For @samuel25009: ..."
            # Extract who the original message was FOR
            if reply_to.text:
                match = re.search(r'🔄 @(\w+)', reply_to.text)
                if not match:
                    match = re.search(r'For @(\w+)', reply_to.text)
                if match:
                    for_username = match.group(1)
                    # If the CURRENT sender IS the person the bot was translating for,
                    # they are REPLYING to the conversation — translate to GROUP LANGUAGE
                    if (msg.from_user.username or '').lower() == for_username.lower():
                        # samuel25009 is replying to "For @samuel25009" → translate to group lang
                        target_lang = group_lang
                        target_display = None  # general broadcast, no specific person
                    else:
                        # A different person is replying → translate for the FOR-person
                        target_lang = db.get_user_lang_by_username(for_username)
                        target_display = for_username
        else:
            # Replying directly to a human → translate to their stored language
            target_lang = db.get_user_lang(replied_user.id)
            target_display = replied_user.username or replied_user.first_name

        # If no stored preference found, fall back to group default
        if not target_lang:
            target_lang = group_lang

        # Only translate if there's an actual lang difference
        if src_lang == target_lang:
            return

        try:
            translated = GoogleTranslator(source='auto', target=target_lang).translate(clean_text)
            if translated.strip().lower() == clean_text.lower() and len(clean_text) > 4:
                return
            if target_display:
                await msg.reply_text(f"🔄 For @{target_display}:\n\n{translated}")
            else:
                # Broadcasting back to group (e.g. samuel replying to his own For@ message)
                await msg.reply_text(f"🔄 @{username} said:\n\n{translated}")
        except Exception as e:
            logger.error(f"Reply translation error: {e}")

        return  # Always stop after handling a reply

    # ─── CASE 2: General message (no reply) ─────────────────────────────────
    # Only trigger bot if the message is NOT in the group's default language
    if src_lang == group_lang:
        return  # Silent — it's the group language, let it flow naturally

    try:
        translated = GoogleTranslator(source='auto', target=group_lang).translate(clean_text)
        if translated.strip().lower() == clean_text.lower() and len(clean_text) > 4:
            return
        await msg.reply_text(f"🔄 @{username} said:\n\n{translated}")
    except Exception as e:
        logger.error(f"General translation error: {e}")


def main():
    token = config.get("bot_token")
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.warning("Bot token not configured properly!")
        return

    application = ApplicationBuilder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("langcodes", langcodes))
    application.add_handler(CommandHandler("languages", languages))
    application.add_handler(CommandHandler("mylanguage", mylanguage))
    application.add_handler(CommandHandler("setlang", setlang))
    application.add_handler(CommandHandler("premium", premium))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("stats", stats))

    application.add_handler(ChatMemberHandler(greet_new_group, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), translate_message))

    logger.info("Bot starting...")
    application.run_polling()


if __name__ == '__main__':
    main()
