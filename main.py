import os
import random
import sqlite3
import logging
import asyncio
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

# ==========================================
# تنظیمات اصلی ربات از طریق محیط سرور
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8894117383:AAFGeDmC1lnY_LoFaah7zTAX7NjriIb2-Tc")
INITIAL_ADMIN_ID = int(os.getenv("ADMIN_ID", "7430881772"))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_FILE = "games.db"

# ==========================================
# ۱. راه‌اندازی دیتابیس (بدون حذف اطلاعات قبلی)
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            total_games INTEGER DEFAULT 0,
            score INTEGER DEFAULT 0,
            rank TEXT DEFAULT '🥉 Bronze I',
            title TEXT DEFAULT 'بدون لقب',
            created_at TEXT,
            last_seen TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dice_history (
            telegram_id INTEGER,
            dice_value INTEGER,
            rolled_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shop (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_name TEXT UNIQUE,
            cost INTEGER
        )
    ''')
    
    try: cursor.execute("ALTER TABLE users ADD COLUMN last_seen TEXT")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE users ADD COLUMN title TEXT DEFAULT 'بدون لقب'")
    except sqlite3.OperationalError: pass
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            telegram_id INTEGER PRIMARY KEY, added_at TEXT
        )
    ''')
    cursor.execute('INSERT OR IGNORE INTO admins (telegram_id, added_at) VALUES (?, ?)', 
                   (INITIAL_ADMIN_ID, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    
    default_titles = [
        ("💀 تاس‌انداز مرگ", 1000),
        ("🔮 ارباب شانس", 1500),
        ("⚔️ گلادیاتور اعظم", 2000),
        ("👑 امپراتور تاس", 3000)
    ]
    for name, cost in default_titles:
        cursor.execute("INSERT OR IGNORE INTO shop (title_name, cost) VALUES (?, ?)", (name, cost))
        
    conn.commit()
    conn.close()

init_db()

RANKS = [
    {"name": "🥉 Bronze I", "minScore": 0},
    {"name": "🥉 Bronze II", "minScore": 50},
    {"name": "🥉 Bronze III", "minScore": 150},
    {"name": "🥈 Silver I", "minScore": 300},
    {"name": "🥈 Silver II", "minScore": 500},
    {"name": "🥈 Silver III", "minScore": 800},
    {"name": "🥇 Gold I", "minScore": 1200},
    {"name": "🥇 Gold II", "minScore": 1700},
    {"name": "🥇 Gold III", "minScore": 2300},
    {"name": "💎 Diamond I", "minScore": 3200},
    {"name": "💎 Diamond II", "minScore": 4200},
    {"name": "💎 Diamond III", "minScore": 5400},
    {"name": "👑 Master", "minScore": 6500},
    {"name": "🔥 Mythic Legend", "minScore": 7500},
    {"name": "🌌 Immortal Champion [Monthly Reset]", "minScore": 8500}
]

DICE_SCORES = {6: 40, 5: 35, 4: 30, 3: 20, 2: 10, 1: 5}

DICE_MOTIVATIONS = {
    6: ["🔥 **شــــــــــش ملوووووووک! میدان نبرد به آتش کشیده شد!**", "😎 شش چرخ روزگار به کامت چرخید! فوق‌العاده بود!"],
    5: ["⚡ **بسیار عالی! شانس با تو همراهه جنگجو!**", "💪 یک پرتاب قدرتمند و بی‌نقص!"],
    4: ["👍 **خوب و مطمئن! قدم به قدم به پیروزی نزدیک‌تر میشی.**", "🛡️ پرتابی محکم برای حفظ موقعیت!"],
    3: ["😐 **معمولی و متوسط... می‌تونست خیلی بهتر باشه!**", "💫 شانس وسط زمین ایستاده، پرتاب بعدی رو محکم‌تر بزن!"],
    2: ["🤏 **امتیاز کمی بود! بوی بدشانسی میاد...**", "🌪️ تاس موافقی نبود، ولی غمت نباشه جنگجو!"],
    1: ["💀 **تاس کفتار گریبان‌گیرت شد! کمترین امتیاز ممکن!**", "❌ سقوط آزاد! تاس کفتار تمام نقشه‌هات رو نقش بر آب کرد!"]
}

def calculate_rank(score):
    current_rank = RANKS[0]["name"]
    for rank in RANKS:
        if score >= rank["minScore"]: current_rank = rank["name"]
        else: break
    return current_rank

def is_user_admin(telegram_id):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    res = cursor.execute('SELECT 1 FROM admins WHERE telegram_id = ?', (telegram_id,)).fetchone()
    conn.close(); return res is not None

def get_or_create_user(telegram_id, username):
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_username = username.replace("@", "") if username else None
    
    user = cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)).fetchone()
    if not user:
        initial_title = 'سازنده ربات' if clean_username == "aria2773" else 'بدون لقب'
        cursor.execute('INSERT INTO users (telegram_id, username, created_at, last_seen, title) VALUES (?, ?, ?, ?, ?)', 
                       (telegram_id, clean_username, now_str, now_str, initial_title))
        conn.commit()
        user = cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)).fetchone()
    else:
        if clean_username == "aria2773" and user['title'] != 'سازنده ربات':
            cursor.execute('UPDATE users SET title = ? WHERE telegram_id = ?', ('سازنده ربات', telegram_id))
            conn.commit()
            user = cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)).fetchone()
            
        if clean_username: cursor.execute('UPDATE users SET last_seen = ?, username = ? WHERE telegram_id = ?', (now_str, clean_username, telegram_id))
        else: cursor.execute('UPDATE users SET last_seen = ? WHERE telegram_id = ?', (now_str, telegram_id))
        conn.commit()
    conn.close(); return user

def update_stats(telegram_id, score_gained, is_win):
    user = get_or_create_user(telegram_id, None)
    new_score = max(0, user['score'] + score_gained)
    new_rank = calculate_rank(new_score)
    win_inc = 1 if is_win else 0
    loss_inc = 0 if is_win else 1
    
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute('''
        UPDATE users SET score = ?, rank = ?, wins = wins + ?, losses = losses + ?, total_games = total_games + 1, last_seen = ?
        WHERE telegram_id = ?
    ''', (new_score, new_rank, win_inc, loss_inc, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), telegram_id))
    conn.commit(); conn.close()
    return {"old_rank": user['rank'], "new_rank": new_rank, "rank_changed": new_rank != user['rank']}

def get_top_players():
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
    top_users = cursor.execute('''
        SELECT telegram_id, username, rank, title, score 
        FROM users 
        WHERE username IS NOT NULL 
        ORDER BY score DESC, total_games DESC 
        LIMIT 10
    ''').fetchall()
    conn.close(); return top_users

# ==========================================
# ۲. سیستم کنترل‌ها و منوی اصلی دکمه‌ای ثابت
# ==========================================
USER_COOLDOWNS = {}
USER_LAST_MESSAGE_TIME = {}  # برای سیستم قفل اسپم ۶۰ ثانیه‌ای
COOLDOWN_TIME = 1.5
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

async def check_cooldown(update: Update) -> bool:
    user_id = update.effective_user.id
    now = datetime.now().timestamp()
    if user_id in USER_COOLDOWNS and now < USER_COOLDOWNS[user_id]:
        if update.message:
            await update.message.reply_text('⚡ **آرام‌تر! چند لحظه صبر کن.**')
        return False
    USER_COOLDOWNS[user_id] = now + COOLDOWN_TIME
    return True

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    user = update.effective_user
    get_or_create_user(user.id, user.username if user.username else user.first_name)
    
    await update.message.reply_markdown(
        f"🔥 **سلام {user.first_name}! به نسخه جدید و ارتقایافته نبرد تاس خوش آمدی!**\n\n"
        f"تاس‌ها عادلانه شده‌اند، رنک‌های ماهانه لجند فعال شده و سیستم حمله بحرانی منتظر پرتاب‌های توست! ⚔️",
        reply_markup=get_main_menu_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    help_text = (
        "⚔️ 🔴 **لیست فرمان‌های نبرد کلوب تاس (آپدیت بزرگ)** 🔴 ⚔️\n\n"
        "🎲 `🎲 پرتاب تاس` — پرتاب تاس انفرادی (با شانس ۳ برابری در صورت تکرار تاس)\n"
        "⚔️ `/duel [راند]` — **دوئل رگباری در گروه** (حداکثر تا ۶ راند، دارای ۱۵ ثانیه استراحت بعد نبرد)\n"
        "🏪 `🏪 بازارچه لقب` — بازارچه لقب‌های اضافه شده توسط مدیریت\n"
        "👤 `👤 پروفایل من` — نمایش رنک و کارنامه جنگی\n"
        "🏆 `🏆 تالار افتخارات` — جدول مشاهیر و رنک‌های برتر ماهانه\n"
    )
    if is_user_admin(update.effective_user.id): help_text += "⚙️ `/admin` — کنترل پنل فوق پیشرفته مدیریت"
    await update.message.reply_markdown(help_text, reply_markup=get_main_menu_keyboard())

# ==========================================
# سیستم مدیریت پرتاب‌ها و حمله بحرانی
# ==========================================
def register_and_check_critical(telegram_id, current_dice):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO dice_history (telegram_id, dice_value, rolled_at) VALUES (?, ?, ?)", (telegram_id, current_dice, now_str))
    
    history = cursor.execute('''
        SELECT dice_value FROM dice_history 
        WHERE telegram_id = ? 
        ORDER BY rolled_at DESC LIMIT 3
    ''', (telegram_id,)).fetchall()
    
    is_critical = False
    if len(history) == 3:
        if history[0][0] == history[1][0] == history[2][0]:
            is_critical = True
            cursor.execute("DELETE FROM dice_history WHERE telegram_id = ?", (telegram_id,))
            
    conn.commit(); conn.close()
    return is_critical

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    user_id = update.effective_user.id
    user_data = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    title_tag = f" [{user_data['title']}]" if user_data['title'] != 'بدون لقب' else ""
    
    dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id)
    dice_value = dice_msg.dice.value
    await asyncio.sleep(3)
    
    base_score = DICE_SCORES[dice_value]
    is_critical = register_and_check_critical(user_id, dice_value)
    
    if is_critical:
        score_gained = (dice_value * 3) * 3
        motivation = f"⚡💥 **حمله بحرانی تاس رخ داد!!!** 💥⚡\nسه پرتاب متوالی تو عدد 〖 **{dice_value}** 〗 بود! قدرت پرتاب تو ۳ برابر شد!"
    else:
        score_gained = base_score
        motivation = random.choice(DICE_MOTIVATIONS[dice_value])
    
    result = update_stats(user_id, score_gained, True)
    
    response = (
        f"👤 **مبارز:** {user_data['username']}{title_tag}\n"
        f"🎲 **تاس:** 〖 **{dice_value}** 〗\n"
        f"📢 {motivation}\n"
        f"🏆 **امتیاز کسب شده:** {score_gained:+} XP"
    )
    if result["rank_changed"]: response += f"\n🎖️ **تغییر رتبه به: {result['new_rank']}**"
    await update.message.reply_markdown(response, reply_markup=get_main_menu_keyboard())

# ==========================================
# ۳. سیستم دوئل گروهی با محدودیت‌های سرور
# ==========================================
async def duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p1 = update.effective_user
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ برای شروع دوئل گروهی، باید این دستور را روی پیام حریف ریپلای کنید!")
        return

    p2 = update.message.reply_to_message.from_user
    
    now = datetime.now().timestamp()
    if p1.id in DUEL_COOLDOWNS and now < DUEL_COOLDOWNS[p1.id]:
        left = int(DUEL_COOLDOWNS[p1.id] - now)
        await update.message.reply_text(f"⏳ **محدودیت ترافیک سرور!** برای حفظ سرعت ربات، تا {left} ثانیه دیگر نمی‌توانی دوئل جدیدی استارت کنی.")
        return

    p2_msg_id = update.message.reply_to_message.message_id
    p1_msg_id = update.message.message_id

    if p1.id == p2.id:
        await update.message.reply_text("❌ نمی‌توانی با خودت دوئل کنی!")
        return
    if p2.is_bot: return

    rounds = 3
    if context.args:
        try:
            rounds = int(context.args[0])
            if rounds < 1: rounds = 3
            if rounds > 6:
                await update.message.reply_text("⚠️ **سقف مجاز راندها ۶ است!** تعداد راندها به ۶ تغییر یافت تا سرعت ربات کم نشود.")
                rounds = 6
        except ValueError: pass

    p1_name = p1.username if p1.username else p1.first_name
    p2_name = p2.username if p2.username else p2.first_name

    get_or_create_user(p1.id, p1_name)
    get_or_create_user(p2.id, p2_name)

    keyboard = [[
        InlineKeyboardButton("⚔️ قبول می‌کنم", callback_data=f"gduel_yes_{p1.id}_{p2.id}_{rounds}_{p1_msg_id}_{p2_msg_id}"),
        InlineKeyboardButton("🏳️ نه", callback_data=f"gduel_no_{p2.id}")
    ]]
    
    await update.message.reply_markdown(
        f"⚔️ **درخواست دوئل گروهی!**\n\n👤 **شروع‌کننده:** {p1_name}\n🎯 **حریف:** {p2_name}\n🏁 **راند:** {rounds} (حداکثر ۶)\n\nآیا چالش را قبول می‌کنی؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==========================================
# ۴. سیستم تاپ پلیرها + دوئل اختصاصی پیوی (PvP)
# ==========================================
async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_players = get_top_players()
    if not top_players:
        if update.message:
            await update.message.reply_text("📊 تالار افتخارات خالی است.")
        return "📊 تالار افتخارات خالی است.", []
    
    leaderboard_text = "🏆 **تالار مشاهیر و ۱۰ گلادیاتور برتر کلوب** 🏆\n\n"
    for index, player in enumerate(top_players):
        medals = "👑" if index == 0 else "⚡" if index == 1 else "🛡️" if index == 2 else "🎖️"
        title_tag = f" ({player['title']})" if player['title'] != 'بدون لقب' else ""
        leaderboard_text += f"{medals} {index + 1}. **{player['username']}**{title_tag}\n  Rank: {player['rank']} | ⭐ {player['score']} XP\n\n"
    
    leaderboard_text += "📢 *رنک‌های بالای ۷۰۰۰ و ۸۰۰۰ کاپ، سر ماه ریست شده و جوایز ویژه می‌گیرند!*"
    keyboard = [[InlineKeyboardButton("⚔️ دوئل با برترین‌ها (مخصوص پیوی)", callback_data="pv_duel_start")]]
    
    if update.message:
        await update.message.reply_markdown(leaderboard_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return leaderboard_text, keyboard

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    if query.data == "pv_duel_start":
        if query.message.chat.type != "private":
            await query.answer("❌ این قابلیت فقط در پیوی (خصوصی با ربات) کار می‌کند!", show_alert=True)
            return
        await query.answer()
        PV_DUEL_STATES[user_id] = "WAITING_FOR_TARGET_NUMBER"
        await query.message.reply_text("🎯 **لطفاً شماره بازیکن مورد نظر خود را از لیست بالا وارد کنید (مثلاً عدد 1 برای نفر اول):**")
        return

    if data[0] == "pvduel":
        action = data[1]
        p1_id = int(data[2])
        p2_id = int(data[3])

        if user_id != p2_id:
            await query.answer("❌ این درخواست برای شما نیست!", show_alert=True)
            return

        if action == "no":
            await query.answer()
            await query.edit_message_text("🏳️ شما درخواست دوئل را رد کردید.")
            try: await context.bot.send_message(chat_id=p1_id, text=f"🏳️ درخواست دوئل شما توسط حریف رد شد.")
            except: pass
            return

        if action == "yes":
            now = datetime.now().timestamp()
            if p1_id in DUEL_COOLDOWNS and now < DUEL_COOLDOWNS[p1_id]:
                await query.answer("❌ حریف شما در حال استراحت است. لحظاتی دیگر تلاش کنید.", show_alert=True)
                return
            
            await query.answer()
            await query.edit_message_text("⚔️ **دوئل آغاز شد! در حال پرتاب تاس‌ها...**")
            try: await context.bot.send_message(chat_id=p1_id, text="⚔️ **حریف درخواست را قبول کرد! نبرد آغاز شد...**")
            except: pass

            conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
            p1_name = cursor.execute('SELECT username FROM users WHERE telegram_id = ?', (p1_id,)).fetchone()['username']
            p2_name = cursor.execute('SELECT username FROM users WHERE telegram_id = ?', (p2_id,)).fetchone()['username']
            conn.close()

            p1_total, p2_total = 0, 0

            try: await context.bot.send_message(chat_id=p1_id, text=f"🎲 پرتاب ۳ تاس شما ({p1_name}):")
            except: pass
            try: await context.bot.send_message(chat_id=p2_id, text=f"🎲 پرتاب ۳ تاس حریف ({p1_name}) برای شما:")
            except: pass

            for _ in range(3):
                try:
                    d_msg = await context.bot.send_dice(chat_id=p1_id)
                    p1_total += d_msg.dice.value
                    await context.bot.send_message(chat_id=p2_id, text=f"تاس {p1_name}: 〖 **{d_msg.dice.value}** 〗")
                except: pass
                await asyncio.sleep(0.5)

            await asyncio.sleep(3.5)

            try: await context.bot.send_message(chat_id=p2_id, text=f"🎲 حالا پرتاب ۳ تاس شما ({p2_name}):")
            except: pass
            try: await context.bot.send_message(chat_id=p1_id, text=f"🎲 پرتاب ۳ تاس حریف ({p2_name}) برای شما:")
            except: pass

            for _ in range(3):
                try:
                    d_msg = await context.bot.send_dice(chat_id=p2_id)
                    p2_total += d_msg.dice.value
                    await context.bot.send_message(chat_id=p1_id, text=f"تاس {p2_name}: 〖 **{d_msg.dice.value}** 〗")
                except: pass
                await asyncio.sleep(0.5)

            await asyncio.sleep(3.5)

            if p1_total > p2_total:
                res_p1 = f"👑 **شما پیروز شدید! ({p1_total} vs {p2_total})** 🎉 (+40 XP)"
                res_p2 = f"💀 **شما باختید! ({p2_total} vs {p1_total})** (+5 XP)"
                update_stats(p1_id, 40, True)
                update_stats(p2_id, 5, False)
            elif p2_total > p1_total:
                res_p1 = f"💀 **شما باختید! ({p1_total} vs {p2_total})** (+5 XP)"
                res_p2 = f"👑 **شما پیروز شدید! ({p2_total} vs {p1_total})** 🎉 (+40 XP)"
                update_stats(p2_id, 40, True)
                update_stats(p1_id, 5, False)
            else:
                res_p1 = res_p2 = f"🤝 **نتیجه مساوی شد! ({p1_total} == {p2_total})**"

            finish_time = datetime.now().timestamp() + 15.0
            DUEL_COOLDOWNS[p1_id] = finish_time
            DUEL_COOLDOWNS[p2_id] = finish_time

            try: await context.bot.send_message(chat_id=p1_id, text=f"🏁 **نتیجه نهایی:**\n\n{res_p1}")
            except: pass
            try: await context.bot.send_message(chat_id=p2_id, text=f"🏁 **نتیجه نهایی:**\n\n{res_p2}")
            except: pass
            return

    if data[0] == "gduel":
        action = data[1]
        if action == "no":
            if user_id != int(data[2]): return
            await query.answer()
            await query.edit_message_text(f"🏳️ دوئل لغو شد. {query.from_user.first_name} عقب نشینی کرد.")
            return
        if action == "yes":
            p1_id, p2_id, rounds = int(data[2]), int(data[3]), int(data[4])
            p1_msg_id, p2_msg_id = int(data[5]), int(data[6])
            if user_id != p2_id: return
            
            now = datetime.now().timestamp()
            if p1_id in DUEL_COOLDOWNS and now < DUEL_COOLDOWNS[p1_id]:
                await query.answer("❌ سازنده چالش هنوز در محدودیت ۱۵ ثانیه‌ای است!", show_alert=True)
                return
                
            await query.answer()
            await query.edit_message_text("⚔️ **نبرد گروهی تایید شد! شروع پرتاب‌ها...**")

            conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
            p1_name = cursor.execute('SELECT username FROM users WHERE telegram_id = ?', (p1_id,)).fetchone()['username']
            p2_name = cursor.execute('SELECT username FROM users WHERE telegram_id = ?', (p2_id,)).fetchone()['username']
            conn.close()

            p1_total, p2_total = 0, 0
            await context.bot.send_message(chat_id=chat_id, text=f"🎲 پرتاب رگباری برای {p1_name}:", reply_to_message_id=p1_msg_id)
            for _ in range(rounds):
                d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p1_msg_id)
                p1_total += d.dice.value
                await asyncio.sleep(0.5)
            await asyncio.sleep(3.5)
            await context.bot.send_message(chat_id=chat_id, text=f" مجموع: **{p1_total}**", reply_to_message_id=p1_msg_id)

            await context.bot.send_message(chat_id=chat_id, text=f"🎲 پرتاب رگباری برای {p2_name}:", reply_to_message_id=p2_msg_id)
            for _ in range(rounds):
                d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p2_msg_id)
                p2_total += d.dice.value
                await asyncio.sleep(0.5)
            await asyncio.sleep(3.5)
            await context.bot.send_message(chat_id=chat_id, text=f" مجموع: **{p2_total}**", reply_to_message_id=p2_msg_id)

            if p1_total > p2_total:
                txt = f"👑 **{p1_name} پیروز شد!** (+40 XP)"
                update_stats(p1_id, 40, True); update_stats(p2_id, 5, False)
            elif p2_total > p1_total:
                txt = f"👑 **{p2_name} پیروز شد!** (+40 XP)"
                update_stats(p2_id, 40, True); update_stats(p1_id, 5, False)
            else: txt = "🤝 **مساوی!**"
            
            finish_time = datetime.now().timestamp() + 15.0
            DUEL_COOLDOWNS[p1_id] = finish_time
            DUEL_COOLDOWNS[p2_id] = finish_time
            
            await context.bot.send_message(chat_id=chat_id, text=txt)

    if data[0] == "admin": await admin_buttons(update, context)
    if data[0] == "buy": await shop_callback(update, context)

# ==========================================
# ۵. مانیتورینگ متن‌ها و اتصال دکمه‌های منو
# ==========================================
async def monitor_messages_and_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # محدودیت اسپم معمولی برای یوزرهایی که ادمین نیستند
    if not is_user_admin(user_id):
        now = datetime.now().timestamp()
        if user_id in USER_LAST_MESSAGE_TIME and (now - USER_LAST_MESSAGE_TIME[user_id]) < 60:
            return
        USER_LAST_MESSAGE_TIME[user_id] = now
    
    # قابلیت اصلی بازیابی رنک‌ها و امتیازات با فرستادن پیام تالار مشاهیر توسط ادمین
    if is_user_admin(user_id) and ("تالار مشاهیر" in text or "۱۰ گلادیاتور برتر" in text) and "XP" in text:
        # استخراج یوزرنیم‌ها و امتیازها با استفاده از Regex هوشمند
        lines = text.split("\n")
        current_username = None
        updated_count = 0
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        for line in lines:
            # پیدا کردن یوزرنیم‌ها (مثلاً کلماتی که بعد از عدد نقطه دار یا مدال می‌آیند)
            user_match = re.search(r'(?:\d+\.\s*|👑|⚡|🛡️|🎖️)\s*([A-Za-z0-9_]+)', line)
            if user_match:
                current_username = user_match.group(1).strip()
            
            # پیدا کردن امتیاز ستاره‌دار یا ساده جلوی عبارات (مانند ⭐ 1847 XP)
            score_match = re.search(r'(?:⭐\s*|\b)(\d+)\s*XP', line)
            if score_match and current_username:
                score_val = int(score_match.group(1))
                rank_val = calculate_rank(score_val)
                
                # بررسی اینکه آیا کاربر از قبل وجود دارد یا خیر (اگر نداشت با آیدی رندوم منفی ساخته می‌شود تا رنکش حفظ شود)
                user_check = cursor.execute("SELECT 1 FROM users WHERE username = ?", (current_username,)).fetchone()
                if user_check:
                    cursor.execute("UPDATE users SET score = ?, rank = ? WHERE username = ?", (score_val, rank_val, current_username))
                else:
                    fake_id = -random.randint(1000000, 9999999)
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute("INSERT INTO users (telegram_id, username, score, rank, created_at, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
                                   (fake_id, current_username, score_val, rank_val, now_str, now_str))
                
                updated_count += 1
                current_username = None  # ریست برای خط بعدی
                
        conn.commit()
        conn.close()
        
        if updated_count > 0:
            await update.message.reply_text(f"✅ **عملیات بازیابی با موفقیت انجام شد!**\nآمار و رنک {updated_count} کاربر با موفقیت در دیتابیس ثبت و همگام‌سازی شد.")
            return
        else:
            await update.message.reply_text("❌ متنی که فرستادی ساختار درستی نداشت یا یوزرنمی توش پیدا نشد!")
            return

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

    if user_id in PV_DUEL_STATES and PV_DUEL_STATES[user_id] == "WAITING_FOR_TARGET_NUMBER":
        del PV_DUEL_STATES[user_id]
        try:
            selection = int(text)
            if selection < 1 or selection > 10: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ عدد نامعتبر است! لطفاً یک شماره بین 1 تا 10 وارد کنید.")
            return

        top_players = get_top_players()
        if selection > len(top_players):
            await update.message.reply_text("❌ این شماره در لیست وجود ندارد!")
            return

        target_player = top_players[selection - 1]
        target_id = target_player['telegram_id']
        target_name = target_player['username']

        if target_id == user_id:
            await update.message.reply_text("❌ نمی‌توانی به خودت درخواست دوئل بدهی!")
            return

        keyboard = [[
            InlineKeyboardButton("⚔️ قبول نبرد", callback_data=f"pvduel_yes_{user_id}_{target_id}"),
            InlineKeyboardButton("🏳️ رد درخواست", callback_data=f"pvduel_no_{user_id}_{target_id}")
        ]]

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"⚔️ **یک درخواست دوئل پیوی دریافت کردید!**\n\n👤 **فرستنده:** @{p_name}\n🎖️ آیا چالش این مبارز را برای یک بازی ۳ رانده می‌پذیرید؟",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            await update.message.reply_markdown(f"🚀 **درخواست دوئل پیوی با موفقیت برای @{target_name} ارسال شد.**")
        except Exception:
            await update.message.reply_text("❌ امکان ارسال پیام به پیوی حریف مقدور نبود!")
        return

    if user_id in ADMIN_STATES:
        state = ADMIN_STATES[user_id]
        
        if state == "WAITING_FOR_BROADCAST":
            del ADMIN_STATES[user_id]
            conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
            rows = cursor.execute('SELECT telegram_id FROM users').fetchall(); conn.close()
            for row in rows:
                try: await context.bot.send_message(chat_id=row[0], text=f"📢 **اطلاعیه مدیریت:**\n\n{text}", parse_mode="Markdown")
                except: continue
            await update.message.reply_text("✅ پیام همگانی فرستاده شد.")
            
        elif state == "WAITING_FOR_CUSTOM_USER":
            ADMIN_STATES[user_id] = f"SET_SCORE_VAL_{text.replace('@', '')}"
            await update.message.reply_text(f"🔢 حالا مقدار امتیازی که می‌خواهی به کاربر اختصاص دهی را به عدد وارد کن (مثلاً 4000):")
            
        elif state.startswith("SET_SCORE_VAL_"):
            target_username = state.replace("SET_SCORE_VAL_", "")
            del ADMIN_STATES[user_id]
            try:
                target_score = int(text)
            except ValueError:
                await update.message.reply_text("❌ خطا! مقدار امتیاز باید یک عدد صحیح باشد.")
                return
                
            new_rank = calculate_rank(target_score)
            conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
            cursor.execute("UPDATE users SET score = ?, rank = ? WHERE username = ?", (target_score, new_rank, target_username))
            changes = conn.total_changes; conn.commit(); conn.close()
            await update.message.reply_text(f"🚀 امتیاز کاربر @{target_username} به {target_score} تغییر کرد و رنک {new_rank} اعمال شد." if changes > 0 else "❌ کاربر یافت نشد.")
            
        elif state == "WAITING_FOR_USERNAME_RESET":
            del ADMIN_STATES[user_id]; target = text.replace("@", "")
            conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
            cursor.execute("UPDATE users SET score = 0, rank = '🥉 Bronze I', title = 'بدون لقب' WHERE username = ?", (target,))
            changes = conn.total_changes; conn.commit(); conn.close()
            await update.message.reply_text("🧹 حساب کاربر صفر شد." if changes > 0 else "❌ پیدا نشد.")
            
        elif state == "WAITING_FOR_SHOP_TITLE":
            ADMIN_STATES[user_id] = f"SHOP_PRICE_{text}"
            await update.message.reply_text("💰 حالا قیمت (به XP) این تگ اختصاصی را وارد کن:")
            
        elif state.startswith("SHOP_PRICE_"):
            new_title = state.replace("SHOP_PRICE_", "")
            del ADMIN_STATES[user_id]
            try:
                price = int(text)
            except ValueError:
                await update.message.reply_text("❌ قیمت باید عدد باشد.")
                return
            conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO shop (title_name, cost) VALUES (?, ?)", (new_title, price))
                conn.commit()
                await update.message.reply_text(f"✅ تگ اختصاصی « {new_title} » با قیمت {price} XP به مغازه اضافه شد.")
            except sqlite3.IntegrityError:
                await update.message.reply_text("❌ این تگ قبلاً در مغازه ثبت شده است.")
            conn.close()

# ==========================================
# ۶. بخش‌های جانبی سیستم فروشگاه و ادمین
# ==========================================
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    win_rate = round((user['wins'] / user['total_games']) * 100, 1) if user['total_games'] > 0 else 0
    title_display = f"🏅 **لقب ویژه:** {user['title']}" if user['title'] != 'بدون لقب' else "🏅 **لقب ویژه:** ندارد"
    
    profile_text = (
        f"🎮 ━━━ **کارت عضویت کلوب نبرد** ━━━ 🎮\n\n"
        f"👤 **نام جنگجو:** {user['username']}\n{title_display}\n"
        f"👑 **رتبه فعلی:** {user['rank']}\n💎 **کل امتیازات:** {user['score']} XP\n\n"
        f"📊 **آمار جنگ‌ها:**\n⚔️ کل مسابقات: {user['total_games']}\n"
        f"🟢 پیروزی: {user['wins']}  |  🔴 شکست: {user['losses']}\n🔥 **نرخ برد:** {win_rate}%\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    if update.message:
        await update.message.reply_markdown(profile_text, reply_markup=get_main_menu_keyboard())
    return profile_text

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
    shop_items = cursor.execute("SELECT id, title_name, cost FROM shop").fetchall(); conn.close()
    
    keyboard = []
    for item in shop_items:
        keyboard.append([InlineKeyboardButton(f"{item['title_name']} 💰 {item['cost']} XP", callback_data=f"buy_{item['id']}")])
    
    if update.message:
        await update.message.reply_text(f"🏪 **به بازارچه ارتقایافته خوش آمدی!**\n💰 موجودی شما: {user['score']} XP", reply_markup=InlineKeyboardMarkup(keyboard))

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = query.from_user.id; data = query.data
    item_id = int(data.split("_")[1])
    
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
    item = cursor.execute("SELECT * FROM shop WHERE id = ?", (item_id,)).fetchone()
    
    if not item:
        conn.close(); return
        
    user = get_or_create_user(user_id, query.from_user.username if query.from_user.username else query.from_user.first_name)
    if user['score'] < item['cost']:
        await query.answer("❌ امتیاز کافی برای خرید این لقب را نداری!", show_alert=True)
        conn.close(); return
    
    new_score = user['score'] - item['cost']
    cursor.execute('UPDATE users SET score = ?, title = ? WHERE telegram_id = ?', (new_score, item['title_name'], user_id))
    conn.commit(); conn.close()
    await query.edit_message_text(f"🎉 **لقب حماسی اختصاصی « {item['title_name']} » برای شما فعال شد!**")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_user_admin(update.effective_user.id): return
    keyboard = [
        [InlineKeyboardButton("📊 لیست کاربران", callback_data="admin_users"), InlineKeyboardButton("🏆 تالار مشاهیر", callback_data="admin_top")],
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"), InlineKeyboardButton("🔄 باز‌یابی پیام رنک", callback_data="admin_restore_msg")],
        [InlineKeyboardButton("🚀 ارتقا امتیاز دلخواه", callback_data="admin_set_score"), InlineKeyboardButton("🧹 صفر کردن امتیاز", callback_data="admin_reset_score")],
        [InlineKeyboardButton("➕ افزودن تگ جدید به شاپ", callback_data="admin_add_shop")],
        [InlineKeyboardButton("❌ بستن پنل", callback_data="admin_close")]
    ]
    await update.message.reply_text("🛠 **اتاق فرمان مدیریت پویای ربات:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = query.from_user.id; data = query.data
    
    if data == "admin_home":
        keyboard = [
            [InlineKeyboardButton("📊 لیست کاربران", callback_data="admin_users"), InlineKeyboardButton("🏆 تالار مشاهیر", callback_data="admin_top")],
            [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"), InlineKeyboardButton("🔄 باز‌یابی پیام رنک", callback_data="admin_restore_msg")],
            [InlineKeyboardButton("🚀 ارتقا امتیاز دلخواه", callback_data="admin_set_score"), InlineKeyboardButton("🧹 صفر کردن امتیاز", callback_data="admin_reset_score")],
            [InlineKeyboardButton("➕ افزودن تگ جدید به شاپ", callback_data="admin_add_shop")],
            [InlineKeyboardButton("❌ بستن پنل", callback_data="admin_close")]
        ]
        await query.edit_message_text("🛠 **اتاق فرمان مدیریت پویای ربات:**", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "admin_users":
        conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        users = cursor.execute('SELECT username, score, rank FROM users ORDER BY score DESC LIMIT 15').fetchall(); conn.close()
        txt = "📊 **آمار کاربران برتر:**\n\n"
        for idx, u in enumerate(users): txt += f"{idx+1}. 👤 @{u['username']} | ⭐ {u['score']} XP | {u['rank']}\n"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))
    elif data == "admin_top":
        text, kb = await top_command(update, context)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))
    elif data == "admin_restore_msg":
        restore_text = (
            "🏆 **تالار مشاهیر و ۱۰ گلادیاتور برتر کلوب** 🏆\n\n"
            "👑 1. MSTVIOF\n  Rank: 🥇 Gold II | ⭐ 1847 XP\n\n"
            "⚡ 2. bardia790\n  Rank: 🥇 Gold I | ⭐ 1690 XP\n\n"
            "🛡️ 3. Meemahyar\n  Rank: 🥈 Silver III | ⭐ 905 XP\n\n"
            "🎖️ 4. aria2773\n  Rank: 🥉 Bronze I | ⭐ 0 XP\n\n"
            "📢 رنک‌های بالای ۷۰۰۰ و ۸۰۰۰ کاپ، سر ماه ریست شده و جوایز ویژه می‌گیرند!\n\n"
            "💡 *این پیام نمونه است. شما به عنوان ادمین می‌توانید هر پیامی که ساختار مشابه بالا و حاوی امتیازات XP دارد را بفرستید تا دیتابیس خودکار آپدیت شود.*"
        )
        await query.edit_message_text(restore_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))
    elif data == "admin_broadcast":
        ADMIN_STATES[user_id] = "WAITING_FOR_BROADCAST"
        await query.edit_message_text("📢 متن پیام همگانی خود را ارسال کنید:")
    elif data == "admin_set_score":
        ADMIN_STATES[user_id] = "WAITING_FOR_CUSTOM_USER"
        await query.edit_message_text("👤 نام کاربری فرد مورد نظر را بدون @ بفرستید:")
    elif data == "admin_reset_score":
        ADMIN_STATES[user_id] = "WAITING_FOR_USERNAME_RESET"
        await query.edit_message_text("🧹 نام کاربری فرد مورد نظر را بدون @ بفرستید:")
    elif data == "admin_add_shop":
        ADMIN_STATES[user_id] = "WAITING_FOR_SHOP_TITLE"
        await query.edit_message_text("✨ نام تگ اختصاصی جدید را بفرستید (مثلاً: 👑 امپراتور تاس):")
    elif data == "admin_close":
        await query.edit_message_text("🔒 پنل مدیریت بسته شد.")
    await query.answer()

# ==========================================
# ۷. تابع اصلی اجرا کننده (Main)
# ==========================================
def main():
    if BOT_TOKEN == "YOUR_DEFAULT_TOKEN_IF_NOT_SET": return
    application = Application.builder().token(BOT_TOKEN).job_queue(None).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("dice", dice_command))
    application.add_handler(CommandHandler("duel", duel_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("top", top_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("shop", shop_command))

    application.add_handler(CallbackQueryHandler(handle_callbacks, pattern="^(pv_duel_start|pvduel_|gduel_|buy_)"))
    application.add_handler(CallbackQueryHandler(admin_buttons, pattern="^admin_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, monitor_messages_and_inputs))

    print("🚀 نسخه جدید آپدیت بزرگ با قابلیت سینک خودکار پیام فعال شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
