import os
import random
import sqlite3
import logging
import asyncio
import re
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

# =====================================================================
# CONFIGURATION AND LOGGING SYSTEM
# =====================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8894117383:AAFqv00G_eAFkeP0x-UhrENKByEb5U5_MnM")
INITIAL_ADMIN_ID = int(os.getenv("ADMIN_ID", "7430881772"))
DB_FILE = "club_dice.db"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =====================================================================
# ADVANCED DATABASE INITIALIZATION (INTEGRATED)
# =====================================================================
def init_db(admin_id):
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    
    # Create Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        score INTEGER DEFAULT 0,
        rank TEXT DEFAULT '🥉 Bronze I',
        title TEXT DEFAULT 'بدون لقب',
        title_expire TEXT,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        draws INTEGER DEFAULT 0,
        total_games INTEGER DEFAULT 0,
        unlocked_titles TEXT DEFAULT '[]',
        unlocked_items TEXT DEFAULT '{"max_rounds": false, "higher_wager": false, "lucky_dice": 0}',
        created_at TEXT,
        last_seen TEXT
    )
    """)
    
    # Create Redeem Codes Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS redeem_codes (
        code TEXT PRIMARY KEY,
        title_name TEXT,
        max_uses INTEGER,
        current_uses INTEGER DEFAULT 0,
        duration_hours INTEGER
    )
    """)
    
    # Create Redeem History Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS redeem_history (
        telegram_id INTEGER,
        code TEXT,
        used_at TEXT,
        PRIMARY KEY (telegram_id, code)
    )
    """)
    
    # Create Shop Titles Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shop (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title_name TEXT UNIQUE,
        cost INTEGER,
        category TEXT
    )
    """)
    
    # Create Dice History Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dice_history (
        telegram_id INTEGER,
        dice_value INTEGER,
        rolled_at TEXT
    )
    """)
    
    # Create Score Logs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS score_logs (
        telegram_id INTEGER,
        game_type TEXT,
        count INTEGER DEFAULT 0,
        PRIMARY KEY (telegram_id, game_type)
    )
    """)
    
    # Create Active Event Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS active_event (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER,
        event_name TEXT,
        end_time TEXT,
        extra_data TEXT,
        reward_type TEXT,
        reward_value TEXT
    )
    """)
    
    # Create Offline Duels (Challenge Links) Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS offline_duels (
        challenge_id TEXT PRIMARY KEY,
        creator_id INTEGER,
        creator_name TEXT,
        target_id INTEGER,
        rounds INTEGER,
        wager INTEGER,
        creator_dice_sum INTEGER DEFAULT 0,
        status TEXT DEFAULT 'PENDING',
        created_at TEXT
    )
    """)
    
    # Insert Initial Admin
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT OR IGNORE INTO users (telegram_id, username, score, rank, created_at, last_seen)
    VALUES (?, 'Admin', 0, '🥉 Bronze I', ?, ?)
    """, (admin_id, current_time_str, current_time_str))
    
    connection.commit()
    connection.close()

init_db(INITIAL_ADMIN_ID)

# =====================================================================
# HARDCORE RANKING SYSTEM LOGIC
# =====================================================================
def calculate_rank(score, telegram_id=None):
    if telegram_id is not None:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        top_10_players = cursor.execute("SELECT telegram_id FROM users ORDER BY score DESC, telegram_id ASC LIMIT 10").fetchall()
        conn.close()
        
        top_10_ids = []
        for row in top_10_players:
            top_10_ids.append(row['telegram_id'])
            
        if score >= 10000 and telegram_id in top_10_ids:
            return "👑 God of Dice (Infinity)"

    if score >= 10000:
        return "🏆 Legend"
    elif score >= 8000:
        return "💎 Diamond III"
    elif score >= 7000:
        return "💎 Diamond II"
    elif score >= 6000:
        return "💎 Diamond I"
    elif score >= 5000:
        return "🔮 Platinum III"
    elif score >= 4000:
        return "🔮 Platinum II"
    elif score >= 3500:
        return "🔮 Platinum I"
    elif score >= 2800:
        return "🎖️ Gold III"
    elif score >= 2200:
        return "🎖️ Gold II"
    elif score >= 1600:
        return "🎖️ Gold I"
    elif score >= 1100:
        return "🛡️ Silver III"
    elif score >= 700:
        return "🛡️ Silver II"
    elif score >= 400:
        return "🛡️ Silver I"
    elif score >= 200:
        return "🥉 Bronze III"
    elif score >= 100:
        return "🥉 Bronze II"
    else:
        return "🥉 Bronze I"

def update_stats(telegram_id, score_change, game_result):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    user = cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not user:
        conn.close()
        return None
        
    current_score = user['score']
    
    # Kings League Hardcore Mechanism (Score >= 10000)
    if current_score >= 10000 and game_result in ['win', 'loss']:
        if game_result == 'win':
            score_change = 80
        elif game_result == 'loss':
            score_change = -100

    new_score = current_score + score_change
    if new_score < 0:
        new_score = 0
        
    new_rank = calculate_rank(new_score, telegram_id)
    rank_changed = (new_rank != user['rank'])
    
    w_inc = 1 if game_result == 'win' else 0
    l_inc = 1 if game_result == 'loss' else 0
    d_inc = 1 if game_result == 'draw' else 0
    g_inc = 1 if game_result in ['win', 'loss', 'draw'] else 0
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    UPDATE users SET 
        score = ?, rank = ?, wins = wins + ?, losses = losses + ?, draws = draws + ?, 
        total_games = total_games + ?, last_seen = ? 
    WHERE telegram_id = ?
    """, (new_score, new_rank, w_inc, l_inc, d_inc, g_inc, now_str, telegram_id))
    
    conn.commit()
    conn.close()
    return {"rank_changed": rank_changed, "new_rank": new_rank}

def get_or_create_user(telegram_id, username):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    user = cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    
    if not user:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
        INSERT INTO users (telegram_id, username, score, rank, created_at, last_seen)
        VALUES (?, ?, 0, '🥉 Bronze I', ?, ?)
        """, (telegram_id, username, now_str, now_str))
        conn.commit()
        user = cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        
    conn.close()
    return dict(user)

def is_user_admin(telegram_id):
    if telegram_id == INITIAL_ADMIN_ID:
        return True
    return False

def get_top_players():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    players = cursor.execute("SELECT * FROM users ORDER BY score DESC, telegram_id ASC LIMIT 10").fetchall()
    conn.close()
    
    result_list = []
    for p in players:
        result_list.append(dict(p))
    return result_list

# =====================================================================
# CONSTANTS, DICTIONARIES AND GLOBAL DICTS
# =====================================================================
DICE_SCORES = {1: -5, 2: 5, 3: 10, 4: 15, 5: 25, 6: 40}
CAT_NAMES = {"normal": "لقب عادی", "epic": "لقب افسانه‌ای", "legendary": "لقب لجندری"}

DICE_MOTIVATIONS = {
    6: [
        "🔥 **شــــــــــش ملوووووووک! میدان نبرد به آتش کشیده شد!**", 
        "😎 شش چرخ روزگار به کامت چرخید! فوق‌العاده بود!"
    ],
    5: [
        "⚡ **بسیار عالی! شانس با تو همراهه جنگجو!**", 
        "💪 یک پرتاب قدرتمند و بی‌نقص!"
    ],
    4: [
        "👍 **خوب و مطمئن! قدم به قدم به پیروزی نزدیک‌تر میشی.**", 
        "🛡️ پرتابی محکم برای حفظ موقعیت!"
    ],
    3: [
        "😐 **معمولی و متوسط... می‌تونست خیلی بهتر باشه!**", 
        "💫 شانس وسط زمین ایستاده، پرتاب بعدی رو محکم‌تر بزن!"
    ],
    2: [
        "🤏 **امتیاز کمی بود! بوی بدشانسی میاد...**", 
        "🌪️ تاس موافقی نبود، ولی غمت نباشه جنگجو!"
    ],
    1: [
        "💀 **تاس کفتار گریبان‌گیرت شد! سقوط آزاد امتیاز!**", 
        "❌ تاس کفتار تمام نقشه‌هات رو نقش بر آب کرد!"
    ]
}

EVENT_NAMES_LIST = {
    1: "امتیاز دو برابر (Double XP) ⚡",
    2: "تاس شانس اختصاصی 🎲",
    3: "تاس معکوس و دیوانه‌وار 🃏",
    7: "تاس شانسی ناشناس (مخفی) 🎰",
    8: "پادشاه تپه (میدان دوئل) 👑",
    14: "انتقام خونین در کلوب 🩸",
    15: "جمعه سیاه بازارچه (تخفیف ویژه) 🛒",
    22: "چالش روزانه گلادیاتورها 🎯"
}

USER_DICE_COUNT = {}
USER_DUEL_COUNT = {}
USER_MUTE_TIMEOUT = {}
DUEL_COOLDOWNS = {}
ADMIN_STATES = {}
PV_DUEL_STATES = {}

def get_main_menu_keyboard():
    keyboard = [
        [KeyboardButton("🎲 پرتاب تاس"), KeyboardButton("👤 پروفایل من")],
        [KeyboardButton("🏆 تالار افتخارات"), KeyboardButton("🏪 بازارچه لقب")],
        [KeyboardButton("ℹ️ راهنمای کلوب")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def check_spam_and_mute(update: Update, action_type: str) -> bool:
    user_id = update.effective_user.id
    now = datetime.now().timestamp()
    
    if user_id in USER_MUTE_TIMEOUT:
        if now < USER_MUTE_TIMEOUT[user_id]:
            return False
        else:
            del USER_MUTE_TIMEOUT[user_id]
            USER_DICE_COUNT[user_id] = 0
            USER_DUEL_COUNT[user_id] = 0

    if action_type == "dice":
        USER_DICE_COUNT[user_id] = USER_DICE_COUNT.get(user_id, 0) + 1
        USER_DUEL_COUNT[user_id] = 0
        if USER_DICE_COUNT[user_id] >= 10:
            USER_MUTE_TIMEOUT[user_id] = now + 120
            await update.message.reply_markdown(
                f"💀 **وضعیت سکوت!**\n"
                f"کاربر @{update.effective_user.username} به دلیل پرتاب متوالی ۱۰ تاس، به مدت **۲ دقیقه** از بازی محروم شد!"
            )
            return False
            
    elif action_type == "duel":
        USER_DUEL_COUNT[user_id] = USER_DUEL_COUNT.get(user_id, 0) + 1
        USER_DICE_COUNT[user_id] = 0
        if USER_DUEL_COUNT[user_id] >= 10:
            USER_MUTE_TIMEOUT[user_id] = now + 120
            await update.message.reply_markdown(
                f"💀 **وضعیت سکوت دوئل!**\n"
                f"کاربر @{update.effective_user.username} به دلیل ارسال ۱۰ درخواست دوئل رگباری، به مدت **۲ دقیقه** در لیست سیاه قرار گرفت!"
            )
            return False
            
    return True

def get_current_active_event():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    ev = cursor.execute("SELECT * FROM active_event ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    
    if not ev: 
        return None
    
    end_time = datetime.strptime(ev['end_time'], "%Y-%m-%d %H:%M:%S")
    if datetime.now() > end_time:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM active_event")
        conn.commit()
        conn.close()
        return None
    return ev

# =====================================================================
# USER COMMANDS HANDLERS
# =====================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username if user.username else user.first_name)
    
    if context.args:
        challenge_id = context.args[0]
        await handle_join_offline_duel(update, context, challenge_id)
        return

    welcome_text = (
        f"⚔️ **به قلمرو خونین و بی‌رحم «نبرد تاس» خوش آمدی، {user.first_name}!** ⚔️\n\n"
        f"اینجا جایی نیست که با خواهش و تمنا امتیاز جمع کنی! اینجا کلوپ گلادیاتورهاست؛\n"
        f"زیرساخت ربات به قدرتمندترین شبکه پایگاه داده متصل شده تا بازی بدون لَگ و با امنیت ۱۰۰٪ اجرا بشه! 🔥\n\n"
        f"⚡ **تاس‌های عادلانه مستقر شدن، بازارچه تگ‌های جنگی آمادست و حریف‌ها دندون تیز کردن!**"
    )
    
    ev = get_current_active_event()
    if ev:
        text_btn = "🕹️ بخش ایونت (فعال 🔥)"
    else:
        text_btn = "🕹️ بخش ایونت"
        
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(text_btn, callback_data="user_check_event")]])
    
    await update.message.reply_markdown(welcome_text, reply_markup=get_main_menu_keyboard())
    await update.message.reply_text("✨ جهت بررسی رویدادها و چالش‌های زنده کلوب دکمه زیر را لمس کنید:", reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "⚔️ 🔴 **لیست فرمان‌های نبرد کلوب تاس (آپدیت بزرگ جهنمی)** 🔴 ⚔️\n\n"
        "🎲 `🎲 پرتاب تاس` — پرتاب تاس انفرادی با شانس حمله بحرانی\n"
        "⚔️ `/duel [راند] [مقدار شرط]` — **دوئل شرطی گروهی** (حداکثر تا ۶ راند، شرط تا سقف ۵۰ امتیاز پایه)\n"
        "🔥 `/oduel [آیدی_حریف] [راند] [شرط]` — **دوئل غیابی** و دریافت لینک اختصاصی چلنج\n"
        "🏪 `🏪 بازارچه لقب` — خرید تگ‌ها و آیتم‌های استراتژیک جدید فروشگاه\n"
        "👤 `👤 پروفایل من` — کارنامه جنگی + دکمه شیشه‌ای انتخاب و ویترین لقب‌ها\n"
        "🏆 `🏆 تالار افتخارات` — لیدربرد فوق‌پیشرفته و تگ ابدی [GOD OF DICE]\n"
        "🔑 `/redeem [کد]` — فعال‌سازی کدهای هدیه ادمین\n"
    )
    if is_user_admin(update.effective_user.id): 
        help_text += "\n⚙️ `/admin` — کنترل پنل فوق پیشرفته اتاق فرماندهی ادمین"
        
    await update.message.reply_markdown(help_text, reply_markup=get_main_menu_keyboard())

# =====================================================================
# SOLO DICE AND CRITICAL HIT LOGIC
# =====================================================================
def register_and_check_critical(telegram_id, current_dice):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO dice_history (telegram_id, dice_value, rolled_at) VALUES (?, ?, ?)", (telegram_id, current_dice, now_str))
    
    history = cursor.execute('''
        SELECT dice_value FROM dice_history WHERE telegram_id = ? 
        ORDER BY rolled_at DESC LIMIT 3
    ''', (telegram_id,)).fetchall()
    
    is_critical = False
    if len(history) == 3:
        if history[0][0] == history[1][0] and history[1][0] == history[2][0]:
            is_critical = True
            cursor.execute("DELETE FROM dice_history WHERE telegram_id = ?", (telegram_id,))
            
    conn.commit()
    conn.close()
    return is_critical

def log_score_source(telegram_id, game_type):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO score_logs (telegram_id, game_type, count) VALUES (?, ?, 1)
        ON CONFLICT(telegram_id, game_type) DO UPDATE SET count = count + 1
    ''', (telegram_id, game_type))
    conn.commit()
    conn.close()

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam_and_mute(update, "dice"): 
        return
        
    user_id = update.effective_user.id
    user_data = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    if user_data['title'] != 'بدون لقب':
        title_tag = f" [{user_data['title']}]"
    else:
        title_tag = ""
    
    dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id)
    dice_value = dice_msg.dice.value
    await asyncio.sleep(3)
    
    base_score = DICE_SCORES[dice_value]
    
    # Lucky Dice Item Handler from Shop
    items_data = json.loads(user_data.get('unlocked_items', '{"max_rounds": false, "higher_wager": false, "lucky_dice": 0}'))
    if user_data['score'] < 10000 and dice_value == 1 and items_data.get('lucky_dice', 0) > 0:
        items_data['lucky_dice'] -= 1
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET unlocked_items = ? WHERE telegram_id = ?", (json.dumps(items_data), user_id))
        conn.commit()
        conn.close()
        
        await update.message.reply_markdown("✨ **آیتم تاس شانس فعال شد!** به دلیل آوردن عدد ۱، یک فرصت مجدد خودکار به شما داده شد. در حال پرتاب مجدد تاس...")
        dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id)
        dice_value = dice_msg.dice.value
        await asyncio.sleep(3)
        base_score = DICE_SCORES[dice_value]

    ev = get_current_active_event()
    ev_bonus_text = ""
    
    if ev:
        ev_id = ev['event_id']
        if ev_id == 1: 
            base_score *= 2
            ev_bonus_text = "\n⚡ **[ایونت امتیاز ۲ برابر فعال است]**"
        elif ev_id == 2: 
            ex_data = json.loads(ev['extra_data'])
            if dice_value == int(ex_data.get('dice', 0)):
                base_score += 30
                ev_bonus_text = f"\n🎯 **[ایونت شانس تاس {dice_value}! +30 امتیاز بونوس]**"
        elif ev_id == 3: 
            if dice_value == 1: 
                base_score = 40
            elif dice_value == 6: 
                base_score = -10
            ev_bonus_text = "\n🃏 **[ایونت تاس معکوس فعال است!]**"

    is_critical = register_and_check_critical(user_id, dice_value)
    if is_critical:
        if ev and ev['event_id'] == 1:
            score_gained = ((dice_value * 3) * 3) * 2
        else:
            score_gained = (dice_value * 3) * 3
        motivation = f"⚡💥 **CRITICAL HIT! حمله بحرانی رخ داد!!!** 💥⚡\nسه پرتاب متوالی روی عدد 〖 **{dice_value}** 〗! امتیاز ۳ برابر ارتقا یافت!"
    else:
        score_gained = base_score
        motivation = random.choice(DICE_MOTIVATIONS[dice_value])
    
    if score_gained > 0:
        mode_str = 'win'
    else:
        mode_str = 'loss'
        
    result = update_stats(user_id, score_gained, mode_str)
    log_score_source(user_id, "solo_roll")
    
    if score_gained >= 0:
        sign = "+"
    else:
        sign = ""
        
    response = (
        f"👤 **مبارز:** {user_data['username']}{title_tag}\n"
        f"🎲 **تاس:** 〖 **{dice_value}** 〗\n"
        f"📢 {motivation}\n"
        f"🏆 **تغییرات امتیاز:** {sign}{score_gained} XP{ev_bonus_text}"
    )
    if result and result["rank_changed"]: 
        response += f"\n🎖️ **تغییر رتبه به: {result['new_rank']}**"
        
    await update.message.reply_markdown(response, reply_markup=get_main_menu_keyboard())

# =====================================================================
# GROUP DUEL SYSTEM
# =====================================================================
async def duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam_and_mute(update, "duel"): 
        return
        
    p1 = update.effective_user
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ برای شروع دوئل، باید این دستور را روی پیام حریف ریپلای کنید!")
        return

    p2 = update.message.reply_to_message.from_user
    if p1.id == p2.id or p2.is_bot: 
        return

    p1_data = get_or_create_user(p1.id, p1.username if p1.username else p1.first_name)
    p2_data = get_or_create_user(p2.id, p2.username if p2.username else p2.first_name)

    p1_items = json.loads(p1_data.get('unlocked_items', '{"max_rounds": false, "higher_wager": false, "lucky_dice": 0}'))

    rounds = 3
    wager = 0
    
    if context.args:
        try:
            rounds = int(context.args[0])
            if rounds < 1: 
                rounds = 3
            
            if p1_items.get('max_rounds', False):
                max_allowed_rounds = 20
            else:
                max_allowed_rounds = 6
                
            if rounds > max_allowed_rounds:
                rounds = max_allowed_rounds
                if max_allowed_rounds == 6:
                    await update.message.reply_text("ℹ️ سقف راندها به صورت پیش‌فرض ۶ است. برای افزایش سقف تا ۲۰ راند، آیتم آن را از شاپ تهیه کنید.")
        except ValueError: 
            pass
        
        if len(context.args) > 1:
            try:
                wager = int(context.args[1])
                if wager < 0: 
                    wager = 0
                
                if p1_items.get('higher_wager', False):
                    max_allowed_wager = 500
                else:
                    max_allowed_wager = 50
                    
                if wager > max_allowed_wager:
                    await update.message.reply_text(f"❌ **خطای سقف شرط!** سقف شرط‌بندی فعلی شما حداکثر **{max_allowed_wager} XP** است!")
                    return
            except ValueError: 
                pass

    if wager > 0:
        if p1_data['score'] < wager:
            await update.message.reply_text(f"❌ امتیاز شما کافی نیست! موجودی: {p1_data['score']} XP")
            return
        if p2_data['score'] < wager:
            await update.message.reply_text(f"❌ امتیاز حریف کافی نیست! موجودی حریف: {p2_data['score']} XP")
            return

    p1_name = p1.username if p1.username else p1.first_name
    p2_name = p2.username if p2.username else p2.first_name
    
    if wager > 0:
        wager_text = f"💰 **شرط نبرد:** {wager} XP (مجموعاً {wager * 2} امتیاز وسط زمین!)\n"
    else:
        wager_text = ""

    p1_msg_id = update.message.message_id
    p2_msg_id = update.message.reply_to_message.message_id

    keyboard = [[
        InlineKeyboardButton("⚔️ قبول می‌کنم", callback_data=f"gduel_yes_{p1.id}_{p2.id}_{rounds}_{p1_msg_id}_{p2_msg_id}_{wager}"),
        InlineKeyboardButton("🏳️ نه", callback_data=f"gduel_no_{p2.id}")
    ]]
    
    await update.message.reply_markdown(
        f"⚔️ **درخواست دوئل گروهی!**\n\n"
        f"👤 **شروع‌کننده:** {p1_name}\n"
        f"🎯 **حریف:** {p2_name}\n"
        f"🏁 **راند:** {rounds}\n"
        f"{wager_text}آیا چالش را قبول می‌کنی؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =====================================================================
# OFFLINE DUEL SYSTEM (CHALLENGE LINKS)
# =====================================================================
async def offline_duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ فرمت استفاده: `/oduel [آیدی_عددی_یا_یوزرنیم_حریف] [راند] [شرط]`\nمثال: `/oduel 7430881772 5 30`")
        return
        
    target_input = context.args[0].replace("@", "")
    rounds = 3
    wager = 0
    
    if len(context.args) > 1:
        try: 
            rounds = int(context.args[1])
            if rounds > 20: rounds = 20
            if rounds < 1: rounds = 1
        except ValueError: 
            pass
            
    if len(context.args) > 2:
        try: 
            wager = int(context.args[2])
            if wager < 0: wager = 0
        except ValueError: 
            pass

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if target_input.isdigit():
        target_user = cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (int(target_input),)).fetchone()
    else:
        target_user = cursor.execute("SELECT * FROM users WHERE username = ?", (target_input,)).fetchone()
        
    creator = cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,)).fetchone()
    
    if not target_user:
        await update.message.reply_text("❌ حریف مورد نظر هنوز عضو ربات نشده یا آیدی اشتباه است.")
        conn.close()
        return
        
    if target_user['telegram_id'] == user_id:
        await update.message.reply_text("❌ نمی‌توانی با خودت دوعل غیابی بزنی!")
        conn.close()
        return

    if creator['score'] < wager or target_user['score'] < wager:
        await update.message.reply_text("❌ امتیاز یکی از دو طرف برای این شرط‌بندی کافی نیست!")
        conn.close()
        return

    challenge_id = f"ch_{random.randint(100000, 999999)}"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
    INSERT INTO offline_duels (challenge_id, creator_id, creator_name, target_id, rounds, wager, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, 'CREATOR_ROLLING', ?)
    """, (challenge_id, user_id, creator['username'], target_user['telegram_id'], rounds, wager, now_str))
    conn.commit()
    conn.close()

    await update.message.reply_markdown(
        f"🎲 **تنظیمات نبرد غیابی با موفقیت ثبت شد!**\n\n"
        f"کاربر گرامی، ابتدا باید راندهای تاس خودت را پرتاب کنی.\n"
        f"تعداد راندها: `{rounds}` راند | مبلغ شرط: `{wager}` XP\n\n"
        f"جهت ریختن تاس‌های خود، دکمه زیر را همین حالا بفشارید 👇",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎲 پرتاب تاس‌های من", callback_data=f"oduel_croll_{challenge_id}")]])
    )

async def handle_join_offline_duel(update: Update, context: ContextTypes.DEFAULT_TYPE, challenge_id: str):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    duel = cursor.execute("SELECT * FROM offline_duels WHERE challenge_id = ?", (challenge_id,)).fetchone()
    
    if not duel:
        await update.message.reply_text("❌ این لینک چالش منقضی شده یا وجود ندارد.")
        conn.close()
        return
        
    if duel['status'] != 'WAITING_FOR_TARGET':
        await update.message.reply_text("❌ این چالش قبلاً تکمیل یا منقضی شده است.")
        conn.close()
        return
        
    if duel['target_id'] != user_id:
        await update.message.reply_text("❌ این لینک چالش اختصاصی است و برای آیدی شما صادر نشده است!")
        conn.close()
        return

    p1 = cursor.execute("SELECT score FROM users WHERE telegram_id = ?", (duel['creator_id'],)).fetchone()
    p2 = cursor.execute("SELECT score FROM users WHERE telegram_id = ?", (user_id,)).fetchone()
    
    if p1['score'] < duel['wager'] or p2['score'] < duel['wager']:
        await update.message.reply_text("❌ امتیازات طرفین برای انجام این مبارزه شرطی دیگر کافی نیست!")
        conn.close()
        return

    conn.close()
    
    await update.message.reply_markdown(
        f"⚔️ **شما وارد لینک دوعل غیابی شدید!**\n\n"
        f"👤 **طراح چالش:** {duel['creator_name']}\n"
        f"🏁 **تعداد راندها:** {duel['rounds']}\n"
        f"💰 **مبلغ شرط وسط:** {duel['wager']} XP\n\n"
        f"حریفت قبلاً تاس هاشو ریخته و منتظر توئه! برای شروع پرتاب تاس‌های خودت دکمه زیر رو بزن:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚔️ ریختن تاس و دریافت نتیجه نهایی", callback_data=f"oduel_troll_{challenge_id}")]])
    )

# =====================================================================
# PROFILE & ADVANCED TITLE SELECTOR PANEL
# =====================================================================
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    if user['total_games'] > 0:
        win_rate = round((user['wins'] / user['total_games']) * 100, 1)
    else:
        win_rate = 0
        
    if user['title'] != 'بدون لقب':
        title_display = f"🏅 **لقب ویژه فعال:** {user['title']}"
    else:
        title_display = "🏅 **لقب ویژه:** ندارد"
    
    profile_text = (
        f"🎮 ━━━ **کارت عضویت کلوب نبرد** ━━━ 🎮\n\n"
        f"👤 **نام جنگجو:** {user['username']}\n{title_display}\n"
        f"👑 **رتبه فعلی:** {user['rank']}\n💎 **کل امتیازات:** {user['score']} XP\n\n"
        f"📊 **آمار جنگ‌ها:**\n⚔️ کل مسابقات: {user['total_games']}\n"
        f"🟢 پیروزی: {user['wins']}  |  🤝 مساوی: {user['draws']}  |  🔴 شکست: {user['losses']}\n🔥 **نرخ برد:** {win_rate}%\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    
    keyboard = [[InlineKeyboardButton("👑 انتخاب و ویترین لقب‌ها", callback_data="show_title_selector")]]
    await update.message.reply_markdown(profile_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_title_selector_panel(query, user_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    user = cursor.execute("SELECT unlocked_titles, title FROM users WHERE telegram_id = ?", (user_id,)).fetchone()
    conn.close()
    
    if user['unlocked_titles']:
        titles = json.loads(user['unlocked_titles'])
    else:
        titles = []
        
    if "بدون لقب" not in titles: 
        titles.insert(0, "بدون لقب")
    
    keyboard = []
    for t in titles:
        if user['title'] == t:
            tick = " ✅"
        else:
            tick = ""
        keyboard.append([InlineKeyboardButton(f"{t}{tick}", callback_data=f"set_active_title_{t}")])
        
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="admin_close")])
    await query.edit_message_text("🎭 **ویترین و پنل مدیریت لقب‌های شما:**\nلقب مورد نظر را برای درخشش در پروفایل فعال کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

# =====================================================================
# LEADERBOARD (HALL OF FAME)
# =====================================================================
async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_players = get_top_players()
    if not top_players:
        if update.message: 
            await update.message.reply_text("📊 تالار افتخارات خالی است.")
        return "📊 تالار افتخارات خالی است.", []
    
    leaderboard_text = "🏆 **تالار مشاهیر و ۱۰ گلادیاتور برتر کلوب** 🏆\n\n"
    for index, player in enumerate(top_players):
        if index == 0:
            medals = "👑"
        elif index == 1:
            medals = "⚡"
        elif index == 2:
            medals = "🛡️"
        else:
            medals = "🎖️"
            
        if player['title'] != 'بدون لقب':
            title_tag = f" ({player['title']})"
        else:
            title_tag = ""
            
        leaderboard_text += f"{medals} {index + 1}. **{player['username']}**{title_tag}\n  Rank: {player['rank']} | ⭐ {player['score']} XP\n\n"
    
    leaderboard_text += "📢 *۱۰ نفر اول سیستم که بالاتر از ۱۰,۰۰۰ کاپ باشند، رنک باشکوه Infinity را مال خود می‌کنند!*"
    keyboard = [[InlineKeyboardButton("⚔️ دوئل با برترین‌ها (مخصوص پیوی)", callback_data="pv_duel_start")]]
    
    if update.message:
        await update.message.reply_markdown(leaderboard_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return leaderboard_text, keyboard

# =====================================================================
# ADVANCED MARKETPLACE SHOP SYSTEM
# =====================================================================
async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal"), InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
        [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")],
        [InlineKeyboardButton("🛠️ خرید آیتم‌های ویژه و پرک‌ها", callback_data="shopmain_items_special")]
    ]
    await update.message.reply_text(f"🏪 **به بازارچه شاپ کلوب خوش آمدی!**\n💰 موجودی حساب شما: {user['score']} XP\n\nبخش مورد نظر را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_special_items_shop(query, user_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    user = cursor.execute("SELECT score, unlocked_items FROM users WHERE telegram_id = ?", (user_id,)).fetchone()
    conn.close()
    
    items = json.loads(user['unlocked_items'] if user['unlocked_items'] else '{"max_rounds": false, "higher_wager": false, "lucky_dice": 0}')
    
    if items.get('max_rounds'):
        mr_status = " (خریداری شده)"
    else:
        mr_status = " 💰 300 XP"
        
    if items.get('higher_wager'):
        hw_status = " (خریداری شده)"
    else:
        hw_status = " 💰 500 XP"
        
    ld_count = items.get('lucky_dice', 0)
    
    keyboard = [
        [InlineKeyboardButton(f"🔹 دوعل بی محدودیت (تا ۲۰ راند){mr_status}", callback_data="buyperk_max_rounds")],
        [InlineKeyboardButton(f"🔹 شرط‌بندی بیشتر (تا سقف ۵۰۰){hw_status}", callback_data="buyperk_higher_wager")],
        [InlineKeyboardButton(f"🎲 خرید تاس شانس (دارای {ld_count} عدد) 💰 150 XP", callback_data="buyperk_lucky_dice")],
        [InlineKeyboardButton("🔙 بازگشت به بازارچه", callback_data="shopmain_back")]
    ]
    await query.edit_message_text(f"🛠️ **فروشگاه آیتم‌های کاربردی و استراتژیک:**\nامتیازات خود را به پرک‌های ویژه تبدیل کنید!\n💰 بالانس شما: {user['score']} XP", reply_markup=InlineKeyboardMarkup(keyboard))

# =====================================================================
# CALLBACK QUERY INTERACTION MASTER ENGINE
# =====================================================================
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    await query.answer()

    if data == "show_title_selector":
        await show_title_selector_panel(query, user_id)
        return
        
    if data.startswith("set_active_title_"):
        selected_title = data.replace("set_active_title_", "")
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET title = ? WHERE telegram_id = ?", (selected_title, user_id))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✨ لقب فعال شما با موفقیت به « {selected_title} » تغییر یافت.")
        return

    if data == "shopmain_items_special":
        await show_special_items_shop(query, user_id)
        return

    if data.startswith("buyperk_"):
        perk = data.replace("buyperk_", "")
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        user = cursor.execute("SELECT score, unlocked_items FROM users WHERE telegram_id = ?", (user_id,)).fetchone()
        items = json.loads(user['unlocked_items'] if user['unlocked_items'] else '{"max_rounds": false, "higher_wager": false, "lucky_dice": 0}')
        
        costs = {"max_rounds": 300, "higher_wager": 500, "lucky_dice": 150}
        cost = costs[perk]
        
        if user['score'] < cost:
            await context.bot.send_message(chat_id=chat_id, text="❌ امتیاز شما کافی نیست!")
            conn.close()
            return
            
        if perk == "lucky_dice":
            items['lucky_dice'] = items.get('lucky_dice', 0) + 1
        else:
            if items.get(perk) == True:
                await context.bot.send_message(chat_id=chat_id, text="❌ این پرک را قبلاً خریداری کرده‌اید!")
                conn.close()
                return
            items[perk] = True
            
        cursor.execute("UPDATE users SET score = score - ?, unlocked_items = ? WHERE telegram_id = ?", (cost, json.dumps(items), user_id))
        conn.commit()
        conn.close()
        await context.bot.send_message(chat_id=chat_id, text=f"🎉 آیتم با موفقیت خریداری و در حساب شما فعال شد!")
        await show_special_items_shop(query, user_id)
        return

    if data.startswith("oduel_croll_"):
        challenge_id = data.replace("oduel_croll_", "")
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        duel = cursor.execute("SELECT * FROM offline_duels WHERE challenge_id = ?", (challenge_id,)).fetchone()
        
        if not duel or duel['creator_id'] != user_id or duel['status'] != 'CREATOR_ROLLING':
            conn.close()
            return
            
        await query.edit_message_text("🎲 در حال ریختن راندهای تاس شما به صورت اتوماتیک...")
        
        c_sum = 0
        for _ in range(duel['rounds']):
            d = await context.bot.send_dice(chat_id=chat_id)
            c_sum += d.dice.value
            await asyncio.sleep(2.5)
            
        cursor.execute("UPDATE offline_duels SET creator_dice_sum = ?, status = 'WAITING_FOR_TARGET' WHERE challenge_id = ?", (c_sum, challenge_id))
        conn.commit()
        conn.close()
        
        bot_username = (await context.bot.get_me()).username
        duel_link = f"https://t.me/{bot_username}?start={challenge_id}"
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ **پرتاب‌های شما ثبت شد! (مجموع امتیازات شما: {c_sum})**\n\n"
                 f"🔗 اکنون لینک اختصاصی چلنج زیر را برای حریفت بفرست؛ هر زمان روی آن کلیک کند، مسابقه نهایی می‌شود:\n\n`{duel_link}`",
            parse_mode="Markdown"
        )
        return

    if data.startswith("oduel_troll_"):
        challenge_id = data.replace("oduel_troll_", "")
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        duel = cursor.execute("SELECT * FROM offline_duels WHERE challenge_id = ?", (challenge_id,)).fetchone()
        
        if not duel or duel['target_id'] != user_id or duel['status'] != 'WAITING_FOR_TARGET':
            conn.close()
            return
            
        await query.edit_message_text("⚔️ در حال پرتاب تاس‌های شما و مقایسه نهایی آمار...")
        
        t_sum = 0
        for _ in range(duel['rounds']):
            d = await context.bot.send_dice(chat_id=chat_id)
            t_sum += d.dice.value
            await asyncio.sleep(2.5)
            
        cursor.execute("UPDATE offline_duels SET status = 'COMPLETED' WHERE challenge_id = ?", (challenge_id,))
        
        p1_id = duel['creator_id']
        p2_id = user_id
        wager = duel['wager']
        
        win_xp = 40
        lose_xp = 5
        result_text = f"🏁 **نتیجه نهایی دوعل غیابی منقضی شده:**\n\n👤 {duel['creator_name']}: {duel['creator_dice_sum']} امتیاز\n👤 شما: {t_sum} امتیاز\n\n"
        
        if duel['creator_dice_sum'] > t_sum:
            total_win = win_xp + wager
            total_lose = lose_xp - wager
            result_text += f"🏆 برنده چالش: {duel['creator_name']} (+{total_win} XP)"
            update_stats(p1_id, total_win, 'win')
            update_stats(p2_id, total_lose, 'loss')
            try: 
                await context.bot.send_message(chat_id=p1_id, text=f"🎉 حریفت لینک چلنج رو استارت زد و تو با برتری {duel['creator_dice_sum']} بر {t_sum} برنده شدی! (+{total_win} XP)")
            except: 
                pass
        elif t_sum > duel['creator_dice_sum']:
            total_win = win_xp + wager
            total_lose = lose_xp - wager
            result_text += f"🏆 برنده چالش: شما (+{total_win} XP)"
            update_stats(p2_id, total_win, 'win')
            update_stats(p1_id, total_lose, 'loss')
            try: 
                await context.bot.send_message(chat_id=p1_id, text=f"💀 حریفت لینک چلنج رو استارت زد و تو با نتیجه {duel['creator_dice_sum']} به {t_sum} شکست خوردی! ({total_lose} XP)")
            except: 
                pass
        else:
            result_text += "🤝 نتیجه کاملاً مساوی شد!"
            update_stats(p1_id, 0, 'draw')
            update_stats(p2_id, 0, 'draw')
            try: 
                await context.bot.send_message(chat_id=p1_id, text=f"🤝 دوعل لینک چلنج شما با نتیجه {t_sum} مساوی به پایان رسید.")
            except: 
                pass
            
        conn.commit()
        conn.close()
        await context.bot.send_message(chat_id=chat_id, text=result_text)
        return

    if data == "user_check_event":
        ev = get_current_active_event()
        if not ev:
            await query.answer("❌ در حال حاضر هیچ ایونتی فعال نیست.", show_alert=True)
            return
        end_time = datetime.strptime(ev['end_time'], "%Y-%m-%d %H:%M:%S")
        rem = end_time - datetime.now()
        text = f"🕹️ **رویداد زنده کلوب:**\n\n🔥 **نام:** {ev['event_name']}\n⏳ **زمان باقی‌مانده:** {rem.seconds // 3600} ساعت"
        await query.message.reply_text(text, parse_mode="Markdown")
        return

    if data.startswith("gduel_"):
        parts = data.split("_")
        action = parts[1]
        if action == "no":
            if user_id != int(parts[2]): 
                return
            await query.edit_message_text("🏳️ دوئل توسط حریف لغو شد.")
            return
        if action == "yes":
            p1_id = int(parts[2])
            p2_id = int(parts[3])
            rands = int(parts[4])
            p1_msg = int(parts[5])
            p2_msg = int(parts[6])
            wager = int(parts[7]) if len(parts) > 7 else 0
            
            if user_id != p2_id: 
                return
            
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            p1_chk = cursor.execute('SELECT score, username FROM users WHERE telegram_id = ?', (p1_id,)).fetchone()
            p2_chk = cursor.execute('SELECT score, username FROM users WHERE telegram_id = ?', (p2_id,)).fetchone()
            
            if wager > 0:
                if not p1_chk or p1_chk['score'] < wager or not p2_chk or p2_chk['score'] < wager:
                    await query.answer("❌ موجودی ناکافی!", show_alert=True)
                    conn.close()
                    return
                    
            await query.edit_message_text("⚔️ **نبرد آغاز شد...**")
            p1_total = 0
            p2_total = 0
            
            for _ in range(rands):
                d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p1_msg)
                p1_total += d.dice.value
                await asyncio.sleep(2.5)
            for _ in range(rands):
                d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p2_msg)
                p2_total += d.dice.value
                await asyncio.sleep(2.5)

            win_xp = 40
            lose_xp = 5
            result_text = f"🏁 **نتیجه نهایی:**\n\n👤 {p1_chk['username']}: {p1_total}\n👤 {p2_chk['username']}: {p2_total}\n\n"
            
            if p1_total > p2_total:
                result_text += f"🏆 برنده: {p1_chk['username']} (+{win_xp+wager} XP)"
                update_stats(p1_id, win_xp+wager, 'win')
                update_stats(p2_id, lose_xp-wager, 'loss')
            elif p2_total > p1_total:
                result_text += f"🏆 برنده: {p2_chk['username']} (+{win_xp+wager} XP)"
                update_stats(p2_id, win_xp+wager, 'win')
                update_stats(p1_id, lose_xp-wager, 'loss')
            else:
                result_text += "🤝 مساوی شد!"
                update_stats(p1_id, 0, 'draw')
                update_stats(p2_id, 0, 'draw')
                
            conn.commit()
            conn.close()
            await context.bot.send_message(chat_id=chat_id, text=result_text)
            return

    if data.startswith("shopmain_cat_"):
        cat_type = data.replace("shopmain_cat_", "")
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        shop_items = cursor.execute("SELECT id, title_name, cost FROM shop WHERE category = ?", (cat_type,)).fetchall()
        conn.close()
        
        if not shop_items:
            await query.edit_message_text("🔒 محصولی در این بخش موجود نیست.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="shopmain_back")]]))
            return
            
        keyboard = []
        for item in shop_items:
            keyboard.append([InlineKeyboardButton(f"{item['title_name']} 💰 {item['cost']} XP", callback_data=f"shopbuy_id_{item['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shopmain_back")])
        await query.edit_message_text(f"🛍️ لیست تگ‌های بخش {CAT_NAMES[cat_type]}:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "shopmain_back":
        keyboard = [
            [InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal"), InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
            [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")],
            [InlineKeyboardButton("🛠️ خرید آیتم‌های ویژه و پرک‌ها", callback_data="shopmain_items_special")]
        ]
        await query.edit_message_text("🏪 **بازارچه لقب‌ها و آیتم‌ها**", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("shopbuy_id_"):
        item_id = int(data.split("_")[2])
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        item = cursor.execute("SELECT * FROM shop WHERE id = ?", (item_id,)).fetchone()
        if not item: 
            conn.close()
            return
        
        user = get_or_create_user(user_id, query.from_user.username if query.from_user.username else query.from_user.first_name)
        if user['score'] < item['cost']:
            await context.bot.send_message(chat_id=chat_id, text="❌ امتیاز کافی نداری مشتی!")
            conn.close()
            return
            
        if user.get('unlocked_titles'):
            unlocked = json.loads(user.get('unlocked_titles'))
        else:
            unlocked = []
            
        if item['title_name'] not in unlocked:
            unlocked.append(item['title_name'])
            
        cursor.execute('UPDATE users SET score = score - ?, title = ?, unlocked_titles = ? WHERE telegram_id = ?', 
                       (item['cost'], item['title_name'], json.dumps(unlocked), user_id))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"🎉 تگ ویژه « {item['title_name']} » باز شد و به ویترین لقب‌های شما اضافه گردید!")
        return

    if data.startswith("admin_"): 
        await admin_buttons(update, context)

# =====================================================================
# MESSAGE FILTER & TEXT ROUTING MONITOR
# =====================================================================
async def monitor_messages_and_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: 
        return
        
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    p_name = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    get_or_create_user(user_id, p_name)

    if text == "🎲 پرتاب تاس": 
        await dice_command(update, context)
        return
    elif text == "👤 پروفایل من": 
        await profile_command(update, context)
        return
    elif text == "🏆 تالار افتخارات": 
        await top_command(update, context)
        return
    elif text == "🏪 بازارچه لقب": 
        await shop_command(update, context)
        return
    elif text == "ℹ️ راهنمای کلوب": 
        await help_command(update, context)
        return

    if user_id in ADMIN_STATES:
        state = ADMIN_STATES[user_id]
        if state == "WAITING_FOR_BROADCAST":
            del ADMIN_STATES[user_id]
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            rows = cursor.execute('SELECT telegram_id FROM users').fetchall()
            conn.close()
            for r in rows:
                try: 
                    await context.bot.send_message(chat_id=r[0], text=f"📢 **اطلاعیه جدید مدیریت:**\n\n{text}", parse_mode="Markdown")
                except: 
                    continue
            await update.message.reply_text("✅ پیام فرستاده شد.")
        elif state == "WAITING_FOR_SHOP_TITLE":
            ADMIN_STATES[user_id] = f"SHOP_CAT_{text}"
            keyboard = [[InlineKeyboardButton("🥈 لقب عادی", callback_data=f"setcat_normal_{text}")],
                        [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data=f"setcat_epic_{text}")],
                        [InlineKeyboardButton("👑 لقب لجندری", callback_data=f"setcat_legendary_{text}")]]
            await update.message.reply_text("📂 دسته‌بندی لقب را مشخص کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
        elif state.startswith("SHOP_PRICE_"):
            parts = state.split("_")
            new_title = parts[2]
            cat_type = parts[3]
            del ADMIN_STATES[user_id]
            try: 
                price = int(text)
            except ValueError: 
                return
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO shop (title_name, cost, category) VALUES (?, ?, ?)", (new_title, price, cat_type))
            connection.commit()
            connection.close()
            await update.message.reply_text(f"✅ لقب « {new_title} » به شاپ اضافه شد.")
        return

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.args:
        code = context.args[0].strip()
    else:
        code = update.message.text.replace("/redeem ", "").strip()
        
    if not code: 
        return
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cdata = cursor.execute('SELECT * FROM redeem_codes WHERE code = ?', (code,)).fetchone()
    
    if not cdata or cdata['current_uses'] >= cdata['max_uses']:
        await update.message.reply_text("❌ کد منقضی یا اشتباه است.")
        conn.close()
        return
        
    hist = cursor.execute('SELECT 1 FROM redeem_history WHERE telegram_id = ? AND code = ?', (user_id, code)).fetchone()
    if hist: 
        await update.message.reply_text("❌ قبلاً استفاده کرده‌اید.")
        conn.close()
        return
    
    user = cursor.execute("SELECT unlocked_titles FROM users WHERE telegram_id = ?", (user_id,)).fetchone()
    unlocked = json.loads(user['unlocked_titles'] if user['unlocked_titles'] else '[]')
    if cdata['title_name'] not in unlocked: 
        unlocked.append(cdata['title_name'])
    
    cursor.execute('INSERT INTO redeem_history (telegram_id, code, used_at) VALUES (?, ?, ?)', (user_id, code, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    cursor.execute('UPDATE redeem_codes SET current_uses = current_uses + 1 WHERE code = ?', (code,))
    cursor.execute('UPDATE users SET title = ?, unlocked_titles = ? WHERE telegram_id = ?', (cdata['title_name'], json.dumps(unlocked), user_id))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"🎉 لقب موقت/دائمی **{cdata['title_name']}** به پروفایل و ویترین شما اضافه شد.")

# =====================================================================
# ADMIN PANEL COMMAND SECURITY CONTROL ROOM
# =====================================================================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_user_admin(update.effective_user.id): 
        return
    keyboard = [
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"), InlineKeyboardButton("➕ افزودن تگ جدید", callback_data="admin_add_shop")],
        [InlineKeyboardButton("🔄 ریست تمام ایونت‌ها", callback_data="admin_reset_all_events")],
        [InlineKeyboardButton("❌ بستن پنل", callback_data="admin_close")]
    ]
    await update.message.reply_text("🛠 **اتاق مدیریت پیشرفته کلوب:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    if data == "admin_broadcast":
        ADMIN_STATES[user_id] = "WAITING_FOR_BROADCAST"
        await query.edit_message_text("📢 متن پیام همگانی را ارسال کنید:")
    elif data == "admin_add_shop":
        ADMIN_STATES[user_id] = "WAITING_FOR_SHOP_TITLE"
        await query.edit_message_text("✨ نام تگ اختصاصی جدید را بفرستید:")
    elif data == "admin_close":
        await query.edit_message_text("🔒 پنل مدیریت بسته شد.")
    elif data.startswith("setcat_"):
        parts = data.split("_")
        cat_type = parts[1]
        title_name = parts[2]
        ADMIN_STATES[user_id] = f"SHOP_PRICE_{title_name}_{cat_type}"
        await query.edit_message_text(f"💰 قیمت لقب « {title_name} » را وارد کنید:")

# =====================================================================
# MAIN METHOD METHOD AND POLLING APPLICATION LAUNCHER
# =====================================================================
def main():
    application = Application.builder().token(BOT_TOKEN).job_queue(None).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("duel", duel_command))
    application.add_handler(CommandHandler("oduel", offline_duel_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("redeem", redeem_command))

    application.add_handler(CallbackQueryHandler(handle_callbacks, pattern="^(pv_duel_start|pvduel_|gduel_|user_check_event|oduel_|show_title_selector|set_active_title_|shopmain_|shopbuy_|buyperk_)"))
    application.add_handler(CallbackQueryHandler(admin_buttons, pattern="^(admin_|setcat_)"))
    
    async def mid_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message and update.message.text:
            await monitor_messages_and_inputs(update, context)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mid_filter))

    print("🚀 زیرساخت جدید ربات با دیتابیس ارتقایافته و قوانین لیگ هاردکور Infinity با موفقیت ران شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
