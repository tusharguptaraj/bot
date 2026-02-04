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
#   SHEIN Voucher Bot v4.1
#   Easy Configuration Edition
#   Dev: @SheinAalu x @sheingiveawayghost
# ==========================================

# ⚙️ ========== EASY CONFIGURATION ========== ⚙️
# Change these values according to your needs:

BOT_TOKEN = os.getenv("BOT_TOKEN", "8207313391:AAHv5RxuIj4RF5xoYw8kxPVtqfpCi5Urwhg")

# 🕒 TIMING SETTINGS
CHECKER_DELAY_SECONDS = 2        # Delay between each voucher check (1-3 recommended)
PROTECTOR_INTERVAL_MINUTES = 8   # How often protector checks (5-15 recommended)
PROGRESS_UPDATE_EVERY = 3        # Update progress after N vouchers (1-10)
REQUEST_TIMEOUT_SECONDS = 60     # API request timeout (30-90)

# 🐛 DEBUG SETTINGS
DEBUG_MODE = True                # Show detailed logs (True/False)
SEND_DEBUG_FILE = True           # Send debug log file with results (True/False)

# 💰 VOUCHER VALUES (Edit if new vouchers added)
VOUCHER_VALUES = {
    "SVH": 4000,
    "SV3": 5000,
    "SVC": 1000,
    "SVD": 2000,
    "SVA": 500,
    "SVG": 500
}

# ⚙️ ========== END OF CONFIGURATION ========== ⚙️

# Convert to seconds for internal use
CHECK_INTERVAL_SECONDS = PROTECTOR_INTERVAL_MINUTES * 60

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
        self.cookie_validated = False

def log_debug(message):
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

def validate_cookies(cookie_string):
    """Validate if cookies are working"""
    if not cookie_string or len(cookie_string) < 100:
        return False, "Cookies too short (incomplete)"
    
    test_code = "TESTCODE123"
    headers = get_headers(cookie_string)
    url = "https://www.sheinindia.in/api/cart/apply-voucher"
    payload = {
        "voucherId": test_code,
        "device": {
            "client_type": "mobile_web"
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        
        if response.status_code == 401:
            return False, "Authentication failed (401 - Access denied)"
        
        if response.status_code in [200, 400, 422]:
            try:
                data = response.json()
                if "errorMessage" in data:
                    errors = data.get("errorMessage", {}).get("errors", [])
                    for error in errors:
                        if error.get("type") == "UnauthorizedError":
                            return False, "Unauthorized - Login required or session expired"
                return True, "Cookies validated successfully!"
            except:
                pass
            return True, "Cookies working (got API response)"
        
        return False, f"Unexpected status code: {response.status_code}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"

def get_voucher_value(code):
    prefix = code[:3].upper() if len(code) >= 3 else code
    return VOUCHER_VALUES.get(prefix, None)

def check_voucher(voucher_code, headers):
    url = "https://www.sheinindia.in/api/cart/apply-voucher"
    payload = {
        "voucherId": voucher_code,
        "device": {
            "client_type": "mobile_web"
        }
    }
    
    try:
        log_debug(f"Checking voucher: {voucher_code}")
        response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        
        log_debug(f"Response status for {voucher_code}: {response.status_code}")
        
        try:
            json_data = response.json()
            if DEBUG_MODE:
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
        response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        log_debug(f"Reset voucher {voucher_code}: {response.status_code}")
    except Exception as e:
        log_debug(f"Reset error for {voucher_code}: {str(e)}")

def is_voucher_applicable(status_code, response_data):
    """Check if voucher is valid"""
    log_debug(f"Validating - Status: {status_code}, Data: {response_data}")
    
    if response_data is None:
        return False, "No response data"
    
    # Check for authentication errors
    if "errorMessage" in response_data:
        errors = response_data.get("errorMessage", {}).get("errors", [])
        for error in errors:
            error_type = error.get("type", "")
            if error_type == "UnauthorizedError":
                return False, "⚠️ AUTH ERROR - Cookies expired/invalid"
    
    # 401 = Authentication failed
    if status_code == 401:
        return False, "🔒 Authentication failed (cookies invalid)"
    
    # Success status
    if status_code and 200 <= status_code < 300:
        if "errorMessage" in response_data:
            errors = response_data.get("errorMessage", {}).get("errors", [])
            
            if not errors:
                log_debug("✅ Valid - Status 200 with no errors")
                return True, "Success"
            
            for error in errors:
                error_type = error.get("type", "")
                error_msg = error.get("message", "").lower()
                
                log_debug(f"Error found - Type: {error_type}, Message: {error_msg}")
                
                # Invalid patterns
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
                
                # Minimum cart value = voucher exists
                if "minimum" in error_msg or "cart" in error_msg:
                    return True, f"Valid but: {error_msg}"
        
        # Has voucher data
        if "data" in response_data:
            data = response_data.get("data", {})
            if data and isinstance(data, dict):
                if "voucher" in data or "discount" in data or "voucherId" in data:
                    log_debug("✅ Valid - Has voucher data")
                    return True, "Voucher applied"
        
        # No error = valid
        if "errorMessage" not in response_data:
            log_debug("✅ Valid - Status 200, no error message")
            return True, "Success"
    
    # HTTP errors
    if status_code and status_code >= 400:
        log_debug(f"❌ Invalid - HTTP error {status_code}")
        return False, f"HTTP Error {status_code}"
    
    log_debug("❌ Invalid - Could not determine validity")
    return False, "Unknown status"

def parse_cookies(raw_text):
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
    vouchers = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if line and not line.startswith("===") and not line.startswith("#"):
            vouchers.append(line)
    return vouchers

def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔍 Voucher Checker", callback_data="menu_checker")],
        [InlineKeyboardButton("🛡️ Voucher Protector", callback_data="menu_protector")],
        [InlineKeyboardButton("🍪 Set Cookies", callback_data="menu_cookies")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="menu_help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_keyboard():
    keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="menu_main")]]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "User"
    
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    
    log_debug(f"User {username} ({user_id}) started bot")
    
    welcome_text = (
        "🛍️ **SHEIN Voucher Checker & Protector Bot**\n"
        "**Version 4.1** - Easy Configuration\n\n"
        f"👋 Welcome, {username}!\n\n"
        "**Current Settings:**\n"
        f"⏱️ Checker delay: {CHECKER_DELAY_SECONDS}s\n"
        f"🛡️ Protector interval: {PROTECTOR_INTERVAL_MINUTES} min\n"
        f"🐛 Debug mode: {'ON' if DEBUG_MODE else 'OFF'}\n\n"
        "🔥 **Credits:** @SheinAalu x @sheingiveawayghost\n\n"
        "Choose an option below:"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=get_main_keyboard()
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    elif query.data == "menu_settings":
        text = (
            "⚙️ **Current Settings**\n\n"
            f"**Timing:**\n"
            f"⏱️ Checker delay: {CHECKER_DELAY_SECONDS} seconds\n"
            f"🛡️ Protector interval: {PROTECTOR_INTERVAL_MINUTES} minutes\n"
            f"📊 Progress updates: Every {PROGRESS_UPDATE_EVERY} vouchers\n"
            f"⏰ Request timeout: {REQUEST_TIMEOUT_SECONDS} seconds\n\n"
            f"**Debug:**\n"
            f"🐛 Debug mode: {'ON ✅' if DEBUG_MODE else 'OFF ❌'}\n"
            f"📄 Debug file: {'Enabled ✅' if SEND_DEBUG_FILE else 'Disabled ❌'}\n\n"
            f"**To change settings:**\n"
            f"Edit the configuration at the top of bot file.\n\n"
            f"**Recommended Settings:**\n"
            f"• Fast: 1s delay, 5 min interval\n"
            f"• Balanced: 2s delay, 8 min interval ⭐\n"
            f"• Safe: 3s delay, 15 min interval"
        )
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_back_keyboard()
        )
    
    elif query.data == "menu_cookies":
        text = (
            "🍪 **Cookie Setup**\n\n"
            "**Steps:**\n"
            "1. Login to sheinindia.in\n"
            "2. Add items to cart\n"
            "3. Press F12 → Network tab\n"
            "4. Apply any voucher\n"
            "5. Find 'apply-voucher' request\n"
            "6. Copy Cookie header (500+ chars)\n"
            "7. Send to bot\n\n"
            "Send me your cookies now:"
        )
        session.waiting_for = 'cookies'
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_back_keyboard()
        )
    
    elif query.data == "menu_checker":
        if not session.cookie_string:
            text = "❌ **Set cookies first!**"
            keyboard = [
                [InlineKeyboardButton("🍪 Set Cookies", callback_data="menu_cookies")],
                [InlineKeyboardButton("« Back", callback_data="menu_main")]
            ]
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        text = (
            "🔍 **Voucher Checker**\n\n"
            f"⚙️ Settings: {CHECKER_DELAY_SECONDS}s delay between checks\n\n"
            "Send voucher codes (one per line) or .txt file:"
        )
        session.waiting_for = 'vouchers_check'
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_back_keyboard()
        )
    
    elif query.data == "menu_protector":
        if not session.cookie_string:
            text = "❌ **Set cookies first!**"
            keyboard = [
                [InlineKeyboardButton("🍪 Set Cookies", callback_data="menu_cookies")],
                [InlineKeyboardButton("« Back", callback_data="menu_main")]
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
                [InlineKeyboardButton("« Back", callback_data="menu_main")]
            ]
            text = (
                f"🛡️ **Protection Active!**\n\n"
                f"✅ Protecting {len(session.vouchers)} vouchers\n"
                f"🕒 Interval: {PROTECTOR_INTERVAL_MINUTES} minutes"
            )
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            text = (
                "🛡️ **Voucher Protector**\n\n"
                f"⚙️ Settings: Check every {PROTECTOR_INTERVAL_MINUTES} minutes\n\n"
                "Send voucher codes:"
            )
            session.waiting_for = 'vouchers_protect'
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=get_back_keyboard()
            )
    
    elif query.data == "stop_protection":
        if session.protection_active and session.protection_task:
            await query.edit_message_text("⏸️ Stopping protection...")
            session.protection_task.cancel()
        else:
            await query.answer("Not active!", show_alert=True)
    
    elif query.data == "menu_help":
        text = (
            "ℹ️ **Help**\n\n"
            "**How to change timing:**\n"
            "1. Open bot file in editor\n"
            "2. Find EASY CONFIGURATION section at top\n"
            "3. Change the values:\n"
            "   - CHECKER_DELAY_SECONDS (1-3)\n"
            "   - PROTECTOR_INTERVAL_MINUTES (5-15)\n"
            "4. Save and restart bot\n\n"
            "**Current settings:**\n"
            f"Checker: {CHECKER_DELAY_SECONDS}s\n"
            f"Protector: {PROTECTOR_INTERVAL_MINUTES}min\n\n"
            "Contact: @SheinAalu | @sheingiveawayghost"
        )
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_back_keyboard()
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    
    session = user_sessions[user_id]
    
    # File upload
    if update.message.document:
        if not update.message.document.file_name.endswith('.txt'):
            await update.message.reply_text("❌ Only .txt files!")
            return
        
        file = await context.bot.get_file(update.message.document.file_id)
        content = await file.download_as_bytearray()
        text_content = content.decode('utf-8')
        
        if session.waiting_for == 'vouchers_check':
            await process_voucher_check(update, session, text_content)
        elif session.waiting_for == 'vouchers_protect':
            await process_voucher_protect(update, context, session, text_content)
        return
    
    # Text message
    text = update.message.text
    
    if session.waiting_for == 'cookies':
        cookie_string = parse_cookies(text)
        
        if len(cookie_string) < 100:
            await update.message.reply_text(
                f"❌ **Cookies too short!**\n\n"
                f"Length: {len(cookie_string)} chars\n"
                f"Required: 500+ chars\n\n"
                f"Copy complete cookie string!",
                parse_mode='Markdown'
            )
            return
        
        # Validate
        validation_msg = await update.message.reply_text("🔄 Validating...")
        is_valid, message = validate_cookies(cookie_string)
        
        if is_valid:
            session.cookie_string = cookie_string
            session.cookie_validated = True
            session.waiting_for = None
            
            await validation_msg.edit_text(
                f"✅ **Cookies Validated!**\n\n"
                f"Length: {len(cookie_string)} chars\n"
                f"Status: {message}",
                parse_mode='Markdown'
            )
            await update.message.reply_text("Choose option:", reply_markup=get_main_keyboard())
        else:
            await validation_msg.edit_text(
                f"❌ **Validation Failed!**\n\n"
                f"Error: {message}\n\n"
                f"Get fresh cookies using Network tab method.",
                parse_mode='Markdown'
            )
            await update.message.reply_text("Try again:", reply_markup=get_main_keyboard())
    
    elif session.waiting_for == 'vouchers_check':
        await process_voucher_check(update, session, text)
    
    elif session.waiting_for == 'vouchers_protect':
        await process_voucher_protect(update, context, session, text)
    
    else:
        await update.message.reply_text("Use /start", reply_markup=get_main_keyboard())

async def process_voucher_check(update: Update, session: UserSession, text: str):
    vouchers = parse_vouchers(text)
    
    if not vouchers:
        await update.message.reply_text("❌ No vouchers found!")
        return
    
    progress_msg = await update.message.reply_text(
        f"🔄 **Checking {len(vouchers)} vouchers...**\n\n"
        f"⚙️ Delay: {CHECKER_DELAY_SECONDS}s between checks\n"
        f"⏱️ Est. time: ~{len(vouchers) * CHECKER_DELAY_SECONDS}s",
        parse_mode='Markdown'
    )
    
    headers = get_headers(session.cookie_string)
    valid_codes = []
    invalid_codes = []
    details = []
    
    for i, code in enumerate(vouchers, 1):
        status, data, error = check_voucher(code, headers)
        is_valid, reason = is_voucher_applicable(status, data)
        
        if is_valid:
            valid_codes.append(code)
            details.append(f"{code}: VALID - {reason}")
        else:
            invalid_codes.append(code)
            details.append(f"{code}: INVALID - {reason}")
        
        reset_voucher(code, headers)
        
        # Update progress based on PROGRESS_UPDATE_EVERY setting
        if i % PROGRESS_UPDATE_EVERY == 0 or i == len(vouchers):
            try:
                await progress_msg.edit_text(
                    f"🔄 **Checking...**\n\n"
                    f"Progress: {i}/{len(vouchers)}\n"
                    f"✅ Valid: {len(valid_codes)}\n"
                    f"❌ Invalid: {len(invalid_codes)}",
                    parse_mode='Markdown'
                )
            except:
                pass
        
        # Use configured delay
        await asyncio.sleep(CHECKER_DELAY_SECONDS)
    
    # Save files
    user_id = session.user_id
    valid_file = f"vouchers_{user_id}.txt"
    invalid_file = f"invalid_{user_id}.txt"
    debug_file = f"debug_{user_id}.txt"
    
    with open(valid_file, 'w') as f:
        f.write('\n'.join(valid_codes))
    
    with open(invalid_file, 'w') as f:
        f.write('\n'.join(invalid_codes))
    
    if SEND_DEBUG_FILE:
        with open(debug_file, 'w') as f:
            f.write('\n'.join(details))
    
    # Summary
    summary = (
        f"**📊 Results:**\n\n"
        f"✅ Valid: {len(valid_codes)}\n"
        f"❌ Invalid: {len(invalid_codes)}\n"
        f"📁 Total: {len(vouchers)}\n"
        f"⏱️ Time: ~{len(vouchers) * CHECKER_DELAY_SECONDS}s"
    )
    
    await progress_msg.edit_text(summary, parse_mode='Markdown')
    
    # Send files
    if valid_codes:
        with open(valid_file, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename='vouchers.txt',
                caption=f'✅ Valid ({len(valid_codes)})'
            )
    
    if invalid_codes:
        with open(invalid_file, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename='invalid.txt',
                caption=f'❌ Invalid ({len(invalid_codes)})'
            )
    
    if SEND_DEBUG_FILE and details:
        with open(debug_file, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename='debug.txt',
                caption='🐛 Debug log'
            )
    
    # Cleanup
    try:
        os.remove(valid_file)
        os.remove(invalid_file)
        if SEND_DEBUG_FILE:
            os.remove(debug_file)
    except:
        pass
    
    session.waiting_for = None
    await update.message.reply_text("✅ Complete!", reply_markup=get_main_keyboard())

async def process_voucher_protect(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                   session: UserSession, text: str):
    vouchers = parse_vouchers(text)
    
    if not vouchers:
        await update.message.reply_text("❌ No vouchers!")
        return
    
    session.vouchers = vouchers
    session.protection_active = True
    session.waiting_for = None
    
    await update.message.reply_text(
        f"🛡️ **Protection Started!**\n\n"
        f"✅ Monitoring {len(vouchers)} vouchers\n"
        f"🕒 Interval: {PROTECTOR_INTERVAL_MINUTES} minutes",
        parse_mode='Markdown'
    )
    
    session.protection_task = asyncio.create_task(
        protection_loop(update, context, session)
    )

async def protection_loop(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                         session: UserSession):
    """Protection loop - same as v4 but uses configured interval"""
    cycle = 1
    chat_id = update.effective_chat.id
    
    while session.protection_active:
        try:
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
                await asyncio.sleep(CHECKER_DELAY_SECONDS)
            
            session.last_valid_codes = valid_codes
            session.last_invalid_codes = invalid_codes
            
            # Send update
            now = datetime.datetime.now().strftime("%H:%M:%S")
            next_time = (datetime.datetime.now() + datetime.timedelta(seconds=CHECK_INTERVAL_SECONDS)).strftime("%H:%M:%S")
            
            report = (
                f"🔄 **Cycle #{cycle}**\n\n"
                f"🕒 Time: {now}\n"
                f"✅ Valid: {len(valid_codes)}\n"
                f"❌ Invalid: {len(invalid_codes)}\n"
                f"⏰ Next: {next_time}"
            )
            
            await context.bot.send_message(chat_id=chat_id, text=report, parse_mode='Markdown')
            
            cycle += 1
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            
        except asyncio.CancelledError:
            # Send final files (same as v4)
            break
        except Exception as e:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Error: {str(e)}\n\nRetrying...",
                parse_mode='Markdown'
            )
            await asyncio.sleep(30)

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Set BOT_TOKEN first!")
        return
    
    print("🤖 SHEIN Bot v4.1 - Easy Configuration")
    print("=" * 50)
    print(f"⏱️  Checker delay: {CHECKER_DELAY_SECONDS}s")
    print(f"🛡️  Protector interval: {PROTECTOR_INTERVAL_MINUTES} min")
    print(f"📊 Progress updates: Every {PROGRESS_UPDATE_EVERY} vouchers")
    print(f"🐛 Debug: {'ON' if DEBUG_MODE else 'OFF'}")
    print("=" * 50)
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, handle_message))
    
    print("✅ Bot running!\n")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()