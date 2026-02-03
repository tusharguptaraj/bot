import os
import json
import time
import datetime
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes
)

# ==========================================
#   SHEIN Voucher Checker & Protector Bot
#   Dev: @SheinAalu x @sheingiveawayghost
#   Version 3.0 - Fixed Validation Logic
# ==========================================

from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "I am alive"

def run():
  app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()



BOT_TOKEN = os.getenv("BOT_TOKEN", "8371840106:AAFYhrwxHEdWDFqulOz2FclIr86MHE_DmQI")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL", "300"))
DEBUG_MODE = os.getenv("DEBUG_MODE", "True").lower() == "true"  # Default True for debugging

VOUCHER_VALUES = {
    "SVH": 4000,
    "SV3": 5000,
    "SVC": 1000,
    "SVD": 2000,
    "SVI": 500,
    "SVG": 500
}

# Store user sessions
user_sessions = {}

class UserSession:
    def __init__(self, user_id):
        self.user_id = user_id
        self.cookie_string = ""
        self.protection_active = False
        self.protection_task = None
        self.vouchers = []
        self.waiting_for = None
        self.last_valid_codes = []
        self.last_invalid_codes = []

def log_debug(message):
    """Debug logging"""
    if DEBUG_MODE:
        print(f"[DEBUG {datetime.datetime.now().strftime('%H:%M:%S')}] {message}")

def get_headers(cookie_string):
    return {
        "accept": "application/json",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "content-type": "application/json",
        "origin": "https://www.sheinindia.in",
        "pragma": "no-cache",
        "referer": "https://www.sheinindia.in/cart",
        "sec-ch-ua": "\"Chromium\";v=\"142\", \"Google Chrome\";v=\"142\", \"Not_A Brand\";v=\"99\"",
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": "\"Android\"",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "x-tenant-id": "SHEIN",
        "cookie": cookie_string
    }

def get_voucher_value(code):
    prefix = code[:3].upper() if len(code) >= 3 else code
    return VOUCHER_VALUES.get(prefix, None)

def check_voucher(voucher_code, headers):
    """
    IMPROVED: Check voucher with better response handling
    """
    url = "https://www.sheinindia.in/api/cart/apply-voucher"
    payload = {
        "voucherId": voucher_code,
        "device": {
            "client_type": "mobile_web"
        }
    }
    
    try:
        log_debug(f"Checking voucher: {voucher_code}")
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        
        log_debug(f"Response status for {voucher_code}: {response.status_code}")
        
        try:
            json_data = response.json()
            log_debug(f"Response data for {voucher_code}: {json.dumps(json_data, indent=2)}")
        except json.JSONDecodeError:
            log_debug(f"JSON decode error for {voucher_code}")
            return response.status_code, None, response.text
            
        return response.status_code, json_data, None
    except Exception as e:
        log_debug(f"Check error for {voucher_code}: {str(e)}")
        return None, None, str(e)

def reset_voucher(voucher_code, headers):
    url = "https://www.sheinindia.in/api/cart/reset-voucher"
    payload = {
        "voucherId": voucher_code,
        "device": {
            "client_type": "mobile_web"
        }
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        log_debug(f"Reset voucher {voucher_code}: {response.status_code}")
    except Exception as e:
        log_debug(f"Reset error for {voucher_code}: {str(e)}")

def is_voucher_applicable(status_code, response_data):
    """
    IMPROVED: Better logic to determine if voucher is valid
    
    Returns: (is_valid, reason)
    """
    log_debug(f"Validating - Status: {status_code}, Data: {response_data}")
    
    # If response is None, it's invalid
    if response_data is None:
        return False, "No response data"
    
    # Success status codes (200, 201, etc.)
    if status_code and 200 <= status_code < 300:
        
        # Check if there's an error message
        if "errorMessage" in response_data:
            errors = response_data.get("errorMessage", {}).get("errors", [])
            
            if not errors:
                # No errors means valid
                log_debug("✅ Valid - Status 200 with no errors")
                return True, "Success"
            
            # Check each error
            for error in errors:
                error_type = error.get("type", "")
                error_msg = error.get("message", "").lower()
                
                log_debug(f"Error found - Type: {error_type}, Message: {error_msg}")
                
                # Common invalid voucher messages
                invalid_patterns = [
                    "not applicable",
                    "not valid",
                    "expired",
                    "invalid",
                    "cannot be used",
                    "does not exist",
                    "unavailable",
                    "not found"
                ]
                
                for pattern in invalid_patterns:
                    if pattern in error_msg:
                        log_debug(f"❌ Invalid - Pattern '{pattern}' found")
                        return False, f"Error: {error_msg}"
                
                # If error type is VoucherOperationError but no invalid pattern
                if error_type == "VoucherOperationError":
                    # Could be other issues like minimum cart value
                    log_debug(f"⚠️ Possibly valid but other issue: {error_msg}")
                    # If message doesn't contain invalid patterns, treat as potentially valid
                    if "minimum" in error_msg or "cart" in error_msg:
                        return True, f"Valid but: {error_msg}"
        
        # If we have data field with voucher info, it's likely valid
        if "data" in response_data:
            data = response_data.get("data", {})
            if data and isinstance(data, dict):
                if "voucher" in data or "discount" in data or "voucherId" in data:
                    log_debug("✅ Valid - Has voucher data")
                    return True, "Voucher applied"
        
        # No error message and status 200 = valid
        if "errorMessage" not in response_data:
            log_debug("✅ Valid - Status 200, no error message")
            return True, "Success"
    
    # 4xx/5xx errors
    if status_code and status_code >= 400:
        log_debug(f"❌ Invalid - HTTP error {status_code}")
        return False, f"HTTP Error {status_code}"
    
    # Default to invalid if we can't determine
    log_debug("❌ Invalid - Could not determine validity")
    return False, "Unknown status"

def parse_cookies(raw_text):
    """Parse cookies from JSON string or text"""
    try:
        data = json.loads(raw_text)
        
        if isinstance(data, list):
            cookies = []
            for item in data:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    cookies.append(f"{item['name']}={item['value']}")
            return "; ".join(cookies)
        elif isinstance(data, dict):
            return "; ".join(f"{k}={v}" for k, v in data.items())
    except:
        return raw_text.strip()
    return ""

def parse_vouchers(text):
    """Parse vouchers from text (one per line)"""
    vouchers = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if line and not line.startswith("===") and not line.startswith("#"):
            vouchers.append(line)
    return vouchers

def get_main_keyboard():
    """Main menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("🔍 Voucher Checker", callback_data="menu_checker")],
        [InlineKeyboardButton("🛡️ Voucher Protector", callback_data="menu_protector")],
        [InlineKeyboardButton("🍪 Set Cookies", callback_data="menu_cookies")],
        [InlineKeyboardButton("📊 Statistics", callback_data="menu_stats")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="menu_help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_keyboard():
    """Back to main menu keyboard"""
    keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="menu_main")]]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "User"
    
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    
    log_debug(f"User {username} ({user_id}) started bot")
    
    welcome_text = (
        "🛍️ **SHEIN Voucher Checker & Protector Bot**\n\n"
        f"👋 Welcome, {username}!\n\n"
        "**What I can do:**\n"
        "• 🔍 Check voucher validity instantly\n"
        "• 🛡️ Monitor vouchers 24/7\n"
        "• 💾 Auto-save results to files\n"
        "• 📊 Track your statistics\n\n"
        "**Quick Start:**\n"
        "1. Set your cookies first 🍪\n"
        "2. Choose Checker or Protector\n"
        "3. Send voucher codes\n"
        "4. Get instant results! ⚡\n\n"
        "🔥 **Credits:** @SheinAalu x @sheingiveawayghost\n\n"
        "Choose an option below to begin:"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=get_main_keyboard()
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    
    session = user_sessions[user_id]
    
    if query.data == "menu_main":
        text = "🏠 **Main Menu**\n\nChoose an option:"
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_main_keyboard()
        )
    
    elif query.data == "menu_cookies":
        text = (
            "🍪 **Cookie Setup**\n\n"
            "To use this bot, I need your SHEIN cookies for authentication.\n\n"
            "**How to get cookies:**\n"
            "1. Open SHEIN website in browser\n"
            "2. Login to your account\n"
            "3. Open Developer Tools (F12)\n"
            "4. Go to Application/Storage → Cookies\n"
            "5. Copy all cookies\n\n"
            "**Supported formats:**\n"
            "• JSON format (from extension)\n"
            "• Plain cookie string\n\n"
            "**Example:**\n"
            "`session=abc123; token=xyz789; user_id=12345`\n\n"
            "🔒 Your cookies are stored securely and only used for checking vouchers.\n\n"
            "⚠️ **IMPORTANT:** Make sure you're logged in to SHEIN and have items in cart for testing!"
        )
        session.waiting_for = 'cookies'
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_back_keyboard()
        )
    
    elif query.data == "menu_checker":
        if not session.cookie_string:
            text = (
                "❌ **Cookies Not Set!**\n\n"
                "Please set your cookies first using the '🍪 Set Cookies' option.\n\n"
                "Cookies are required to authenticate with SHEIN API."
            )
            keyboard = [
                [InlineKeyboardButton("🍪 Set Cookies Now", callback_data="menu_cookies")],
                [InlineKeyboardButton("« Back to Menu", callback_data="menu_main")]
            ]
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        text = (
            "🔍 **Voucher Checker**\n\n"
            "Send me voucher codes to check their validity.\n\n"
            "**📝 Formats Accepted:**\n"
            "• One code per line (text message)\n"
            "• Upload .txt file with codes\n\n"
            "**Example:**\n"
            "```\nSVH1234\nSV31234\nSVC1234\nSVD5678```\n\n"
            "**What happens next:**\n"
            "1. I'll check each code with detailed logging ⚡\n"
            "2. Show you real-time results 📊\n"
            "3. Save valid codes to `vouchers.txt` ✅\n"
            "4. Save invalid codes to `invalid.txt` ❌\n\n"
            "⚠️ **Note:** Debug mode is ON, you'll see detailed validation info.\n\n"
            "Ready? Send me the codes! 🚀"
        )
        session.waiting_for = 'vouchers_check'
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_back_keyboard()
        )
    
    elif query.data == "menu_protector":
        if not session.cookie_string:
            text = (
                "❌ **Cookies Not Set!**\n\n"
                "Please set your cookies first using the '🍪 Set Cookies' option."
            )
            keyboard = [
                [InlineKeyboardButton("🍪 Set Cookies Now", callback_data="menu_cookies")],
                [InlineKeyboardButton("« Back to Menu", callback_data="menu_main")]
            ]
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        if session.protection_active:
            keyboard = [
                [InlineKeyboardButton("🛑 Stop Protection", callback_data="stop_protection")],
                [InlineKeyboardButton("📊 View Status", callback_data="protection_status")],
                [InlineKeyboardButton("« Back to Menu", callback_data="menu_main")]
            ]
            text = (
                "🛡️ **Protection Active!**\n\n"
                f"✅ Protecting **{len(session.vouchers)}** vouchers\n"
                f"🕒 Check interval: **{CHECK_INTERVAL_SECONDS//60} minutes**\n"
                f"✔️ Valid codes: **{len(session.last_valid_codes)}**\n"
                f"❌ Invalid codes: **{len(session.last_invalid_codes)}**\n\n"
                "Protection is running in background. You'll receive updates automatically.\n\n"
                "Click below to stop protection or view status."
            )
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            text = (
                "🛡️ **Voucher Protector**\n\n"
                "Continuous monitoring for your vouchers!\n\n"
                "**How it works:**\n"
                f"• Checks every **{CHECK_INTERVAL_SECONDS//60} minutes** ⏱️\n"
                "• Sends you status updates 📬\n"
                "• Notifies of any changes ⚠️\n"
                "• Auto-saves when stopped 💾\n\n"
                "**📝 Send voucher codes:**\n"
                "• One code per line (text)\n"
                "• Upload .txt file\n\n"
                "**Example:**\n"
                "```\nSVH1234\nSV31234\nSVC1234```\n\n"
                "Ready to protect? Send me the codes! 🚀"
            )
            session.waiting_for = 'vouchers_protect'
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=get_back_keyboard()
            )
    
    elif query.data == "stop_protection":
        if session.protection_active and session.protection_task:
            await query.edit_message_text(
                "⏸️ **Stopping Protection...**\n\nPlease wait while I complete the final check.",
                parse_mode='Markdown'
            )
            session.protection_task.cancel()
        else:
            await query.answer("Protection is not active!", show_alert=True)
    
    elif query.data == "protection_status":
        if session.protection_active:
            now = datetime.datetime.now().strftime("%H:%M:%S")
            text = (
                "📊 **Protection Status**\n\n"
                f"🕒 Current time: {now}\n"
                f"🛡️ Status: **Active**\n"
                f"📝 Vouchers: **{len(session.vouchers)}**\n"
                f"✅ Valid: **{len(session.last_valid_codes)}**\n"
                f"❌ Invalid: **{len(session.last_invalid_codes)}**\n"
                f"⏱️ Check interval: **{CHECK_INTERVAL_SECONDS//60} min**\n\n"
                "Protection is running smoothly! 🚀"
            )
            await query.answer(text, show_alert=True)
        else:
            await query.answer("Protection is not active!", show_alert=True)
    
    elif query.data == "menu_stats":
        text = (
            "📊 **Your Statistics**\n\n"
            f"🍪 Cookies: {'✅ Set' if session.cookie_string else '❌ Not set'}\n"
            f"🛡️ Protection: {'✅ Active' if session.protection_active else '⏸️ Inactive'}\n"
            f"📝 Monitored vouchers: **{len(session.vouchers) if session.protection_active else 0}**\n"
            f"✅ Last valid: **{len(session.last_valid_codes)}**\n"
            f"❌ Last invalid: **{len(session.last_invalid_codes)}**\n\n"
            "Keep checking vouchers to see more stats! 📈"
        )
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_back_keyboard()
        )
    
    elif query.data == "menu_help":
        text = (
            "ℹ️ **Help & Information**\n\n"
            "**🔍 Voucher Checker:**\n"
            "Check if voucher codes are valid. Get instant results with categorized files.\n\n"
            "**🛡️ Voucher Protector:**\n"
            f"Monitor vouchers continuously every {CHECK_INTERVAL_SECONDS//60} minutes. Get notifications on changes.\n\n"
            "**🍪 Cookies:**\n"
            "Required for API authentication. Export from your browser.\n\n"
            "**Common Issues:**\n"
            "• If valid codes show as invalid, check:\n"
            "  - Are you logged in to SHEIN?\n"
            "  - Do you have items in cart?\n"
            "  - Are cookies fresh and complete?\n"
            "  - Is the voucher region-specific?\n\n"
            "**📊 Files Generated:**\n"
            "• `vouchers.txt` - Valid voucher codes\n"
            "• `invalid.txt` - Invalid voucher codes\n\n"
            "**💡 Pro Tips:**\n"
            "• Always log in to SHEIN first\n"
            "• Add some items to cart\n"
            "• Use fresh cookies (< 24 hours old)\n"
            "• Check debug logs for details\n\n"
            "**👨‍💻 Developers:**\n"
            "@SheinAalu | @sheingiveawayghost"
        )
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_back_keyboard()
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages and documents"""
    user_id = update.effective_user.id
    
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    
    session = user_sessions[user_id]
    
    # Handle file uploads
    if update.message.document:
        if not update.message.document.file_name.endswith('.txt'):
            await update.message.reply_text(
                "❌ **Invalid file type!**\n\nPlease send only .txt files.",
                parse_mode='Markdown'
            )
            return
        
        file = await context.bot.get_file(update.message.document.file_id)
        content = await file.download_as_bytearray()
        text_content = content.decode('utf-8')
        
        log_debug(f"File uploaded by user {user_id}: {len(text_content)} bytes")
        
        if session.waiting_for == 'vouchers_check':
            await process_voucher_check(update, session, text_content)
        elif session.waiting_for == 'vouchers_protect':
            await process_voucher_protect(update, context, session, text_content)
        return
    
    # Handle text messages
    text = update.message.text
    
    if session.waiting_for == 'cookies':
        cookie_string = parse_cookies(text)
        if cookie_string:
            session.cookie_string = cookie_string
            session.waiting_for = None
            log_debug(f"Cookies set for user {user_id}")
            log_debug(f"Cookie length: {len(cookie_string)} chars")
            await update.message.reply_text(
                "✅ **Cookies Saved Successfully!**\n\n"
                f"Cookie length: {len(cookie_string)} characters\n\n"
                "You can now use:\n"
                "• 🔍 Voucher Checker\n"
                "• 🛡️ Voucher Protector\n\n"
                "⚠️ **Make sure:**\n"
                "- You're logged in to SHEIN\n"
                "- You have items in cart\n"
                "- Cookies are fresh (<24h old)\n\n"
                "Choose an option from the menu below:",
                parse_mode='Markdown',
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ **Invalid Cookie Format!**\n\n"
                "Please try again with valid cookies.",
                parse_mode='Markdown'
            )
    
    elif session.waiting_for == 'vouchers_check':
        await process_voucher_check(update, session, text)
    
    elif session.waiting_for == 'vouchers_protect':
        await process_voucher_protect(update, context, session, text)
    
    else:
        await update.message.reply_text(
            "👋 Please use the buttons below to navigate!\n\n"
            "Send /start to see the main menu.",
            reply_markup=get_main_keyboard()
        )

async def process_voucher_check(update: Update, session: UserSession, text: str):
    """Process voucher checking with improved validation"""
    vouchers = parse_vouchers(text)
    
    if not vouchers:
        await update.message.reply_text(
            "❌ **No Valid Vouchers Found!**\n\n"
            "Please send vouchers in the correct format:\n"
            "• One voucher per line\n"
            "• No empty lines\n\n"
            "Example:\n"
            "`SVH1234\nSV31234\nSVC1234`",
            parse_mode='Markdown'
        )
        return
    
    log_debug(f"Checking {len(vouchers)} vouchers for user {session.user_id}")
    
    progress_msg = await update.message.reply_text(
        f"🔄 **Starting Voucher Check...**\n\n"
        f"📝 Total vouchers: **{len(vouchers)}**\n"
        f"⏱️ Estimated time: **~{len(vouchers) * 2} seconds**\n"
        f"🐛 Debug mode: **ON** (detailed logs)\n\n"
        "Please wait while I check each code...",
        parse_mode='Markdown'
    )
    
    headers = get_headers(session.cookie_string)
    valid_codes = []
    invalid_codes = []
    details = []
    
    results_text = "**📊 Check Results:**\n\n"
    
    for i, code in enumerate(vouchers, 1):
        status, data, error = check_voucher(code, headers)
        
        is_valid, reason = is_voucher_applicable(status, data)
        
        if is_valid:
            val = get_voucher_value(code)
            valid_codes.append(code)
            results_text += f"✅ `{code}` - **VALID** (₹{val if val else '???'})\n"
            details.append(f"{code}: VALID - {reason}")
        else:
            invalid_codes.append(code)
            results_text += f"❌ `{code}` - **INVALID** ({reason})\n"
            details.append(f"{code}: INVALID - {reason}")
        
        reset_voucher(code, headers)
        
        # Update progress
        if i % 3 == 0 or i == len(vouchers):
            try:
                await progress_msg.edit_text(
                    f"🔄 **Checking Vouchers...**\n\n"
                    f"Progress: **{i}/{len(vouchers)}**\n"
                    f"✅ Valid: **{len(valid_codes)}**\n"
                    f"❌ Invalid: **{len(invalid_codes)}**\n\n"
                    f"Current: `{code}`",
                    parse_mode='Markdown'
                )
            except:
                pass
        
        await asyncio.sleep(2)
    
    # Update session stats
    session.last_valid_codes = valid_codes
    session.last_invalid_codes = invalid_codes
    
    # Save files
    user_id = session.user_id
    valid_file = f"vouchers_{user_id}.txt"
    invalid_file = f"invalid_{user_id}.txt"
    debug_file = f"debug_{user_id}.txt"
    
    with open(valid_file, 'w') as f:
        f.write('\n'.join(valid_codes))
    
    with open(invalid_file, 'w') as f:
        f.write('\n'.join(invalid_codes))
    
    with open(debug_file, 'w') as f:
        f.write('\n'.join(details))
    
    # Summary
    summary = (
        f"\n\n**📈 Final Summary:**\n"
        f"✅ Valid: **{len(valid_codes)}** codes\n"
        f"❌ Invalid: **{len(invalid_codes)}** codes\n"
        f"📁 Total: **{len(vouchers)}** checked\n\n"
        f"💰 Total value: **₹{sum(get_voucher_value(c) or 0 for c in valid_codes)}**"
    )
    
    await progress_msg.edit_text(
        results_text + summary,
        parse_mode='Markdown'
    )
    
    # Send files
    if valid_codes:
        with open(valid_file, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename='vouchers.txt',
                caption=f'✅ **Valid Vouchers** ({len(valid_codes)} codes)'
            )
    else:
        await update.message.reply_text(
            "⚠️ **No valid vouchers found!**\n\n"
            "This could mean:\n"
            "• Vouchers are expired/used\n"
            "• Cookies are invalid/expired\n"
            "• You're not logged in\n"
            "• Cart is empty\n\n"
            "Check the debug file for details.",
            parse_mode='Markdown'
        )
    
    if invalid_codes:
        with open(invalid_file, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename='invalid.txt',
                caption=f'❌ **Invalid Vouchers** ({len(invalid_codes)} codes)'
            )
    
    # Send debug file
    with open(debug_file, 'rb') as f:
        await update.message.reply_document(
            document=f,
            filename='debug_log.txt',
            caption='🐛 **Debug Log** (detailed validation info)'
        )
    
    # Cleanup files
    try:
        os.remove(valid_file)
        os.remove(invalid_file)
        os.remove(debug_file)
    except:
        pass
    
    session.waiting_for = None
    
    await update.message.reply_text(
        "✅ **Check Completed!**\n\n"
        "Files sent. Check debug log if results look wrong.\n\n"
        "What would you like to do next?",
        parse_mode='Markdown',
        reply_markup=get_main_keyboard()
    )

async def process_voucher_protect(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                   session: UserSession, text: str):
    """Start voucher protection"""
    vouchers = parse_vouchers(text)
    
    if not vouchers:
        await update.message.reply_text(
            "❌ **No Valid Vouchers Found!**\n\n"
            "Please send vouchers in the correct format.",
            parse_mode='Markdown'
        )
        return
    
    session.vouchers = vouchers
    session.protection_active = True
    session.waiting_for = None
    
    log_debug(f"Protection started for user {session.user_id} with {len(vouchers)} vouchers")
    
    await update.message.reply_text(
        f"🛡️ **Protection Started!**\n\n"
        f"✅ Monitoring **{len(vouchers)}** vouchers\n"
        f"🕒 Check interval: **{CHECK_INTERVAL_SECONDS//60} minutes**\n"
        f"📬 You'll receive updates after each cycle\n\n"
        "Running initial check now...",
        parse_mode='Markdown'
    )
    
    # Start protection loop
    session.protection_task = asyncio.create_task(
        protection_loop(update, context, session)
    )

async def protection_loop(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                         session: UserSession):
    """Background protection loop"""
    cycle = 1
    chat_id = update.effective_chat.id
    
    while session.protection_active:
        try:
            log_debug(f"Protection cycle {cycle} started for user {session.user_id}")
            
            headers = get_headers(session.cookie_string)
            valid_codes = []
            invalid_codes = []
            
            for code in session.vouchers:
                status, data, error = check_voucher(code, headers)
                is_valid, reason = is_voucher_applicable(status, data)
                
                if is_valid:
                    valid_codes.append(code)
                else:
                    invalid_codes.append(code)
                
                reset_voucher(code, headers)
                await asyncio.sleep(2)
            
            # Update session
            session.last_valid_codes = valid_codes
            session.last_invalid_codes = invalid_codes
            
            # Send update
            now = datetime.datetime.now().strftime("%H:%M:%S")
            next_check = (datetime.datetime.now() + 
                         datetime.timedelta(seconds=CHECK_INTERVAL_SECONDS))
            
            report = (
                f"🔄 **Protection Cycle #{cycle}**\n\n"
                f"🕒 Time: `{now}`\n"
                f"✅ Valid: **{len(valid_codes)}** vouchers\n"
                f"❌ Invalid: **{len(invalid_codes)}** vouchers\n"
                f"💰 Total value: **₹{sum(get_voucher_value(c) or 0 for c in valid_codes)}**\n\n"
                f"⏰ Next check at: `{next_check.strftime('%H:%M:%S')}`\n\n"
                "Protection is running... 🛡️"
            )
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=report,
                parse_mode='Markdown'
            )
            
            cycle += 1
            
            # Wait for next cycle
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            
        except asyncio.CancelledError:
            log_debug(f"Protection stopped for user {session.user_id}")
            
            # Final check
            headers = get_headers(session.cookie_string)
            valid_codes = []
            invalid_codes = []
            
            for code in session.vouchers:
                status, data, error = check_voucher(code, headers)
                is_valid, reason = is_voucher_applicable(status, data)
                
                if is_valid:
                    valid_codes.append(code)
                else:
                    invalid_codes.append(code)
                    
                reset_voucher(code, headers)
                await asyncio.sleep(1)
            
            # Save files
            user_id = session.user_id
            valid_file = f"vouchers_{user_id}.txt"
            invalid_file = f"invalid_{user_id}.txt"
            
            with open(valid_file, 'w') as f:
                f.write('\n'.join(valid_codes))
            
            with open(invalid_file, 'w') as f:
                f.write('\n'.join(invalid_codes))
            
            # Send final report
            final_report = (
                "🛑 **Protection Stopped**\n\n"
                f"**Final Status:**\n"
                f"✅ Valid: **{len(valid_codes)}** vouchers\n"
                f"❌ Invalid: **{len(invalid_codes)}** vouchers\n"
                f"💰 Total value: **₹{sum(get_voucher_value(c) or 0 for c in valid_codes)}**\n\n"
                "Sending final files..."
            )
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=final_report,
                parse_mode='Markdown'
            )
            
            # Send files
            if valid_codes:
                with open(valid_file, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename='vouchers.txt',
                        caption=f'✅ **Final Valid Vouchers** ({len(valid_codes)} codes)'
                    )
            
            if invalid_codes:
                with open(invalid_file, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename='invalid.txt',
                        caption=f'❌ **Final Invalid Vouchers** ({len(invalid_codes)} codes)'
                    )
            
            # Cleanup
            try:
                os.remove(valid_file)
                os.remove(invalid_file)
            except:
                pass
            
            session.protection_active = False
            session.vouchers = []
            
            await context.bot.send_message(
                chat_id=chat_id,
                text="✅ Protection session ended. Choose an option:",
                reply_markup=get_main_keyboard()
            )
            
            break
            
        except Exception as e:
            log_debug(f"Error in protection loop: {str(e)}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ **Error in protection cycle:**\n`{str(e)}`\n\nRetrying...",
                parse_mode='Markdown'
            )
            await asyncio.sleep(30)

def main():
    """Start the bot"""
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Error: Please set BOT_TOKEN!")
        return
    
    print("🤖 SHEIN Voucher Bot v3.0 (Fixed Validation)")
    print("=" * 50)
    print(f"✅ Bot Token: {'*' * 20}{BOT_TOKEN[-10:]}")
    print(f"⏱️  Check Interval: {CHECK_INTERVAL_SECONDS//60} minutes")
    print(f"🐛 Debug Mode: {DEBUG_MODE}")
    print("=" * 50)
    print("🚀 Starting bot...\n")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(
        filters.TEXT | filters.Document.ALL, 
        handle_message
    ))
    
    # === YAHAN CHANGE KARNA HAI (EXACT LOCATION) ===
    
    keep_alive()  # <--- Ye line yahan add karni hai
    
    print("✅ Bot is running! Press Ctrl+C to stop.\n")
    
    try:
        # Ye line aapke bot ko chalati hai (polling)
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n\n🛑 Bot stopped by user")

if __name__ == "__main__":
    main()