import os
import random
import logging
import asyncio
import re
import json
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import DictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

# ==========================================
# تنظیمات اصلی ربات و اتصال به دیتابیس PostgreSQL ریل‌وی
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8894117383:AAFqv00G_eAFkeP0x-UhrENKByEb5U5_MnM")
DATABASE_URL = os.getenv("DATABASE_URL")
INITIAL_ADMIN_ID = int(os.getenv("ADMIN_ID", "7430881772"))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_db_connection():
    """برقراری ارتباط با دیتابیس PostgreSQL ریل‌وی"""
    return psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)

def init_db(initial_admin_id=7430881772):
    """ساخت تمام جدول‌های مورد نیاز ربات در PostgreSQL"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # ۱. جدول کاربران کلوب
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            score INT DEFAULT 0,
            rank VARCHAR(50) DEFAULT '🥉 Bronze I',
            title VARCHAR(255) DEFAULT 'بدون لقب',
            title_expire VARCHAR(50) DEFAULT NULL,
            wins INT DEFAULT 0,
            losses INT DEFAULT 0,
            draws INT DEFAULT 0,
            total_games INT DEFAULT 0,
            created_at VARCHAR(50),
            last_seen VARCHAR(50)
        );
        """)

        # ۲. جدول ادمین‌های سیستم
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            telegram_id BIGINT PRIMARY KEY
        );
        """)

        # ۳. جدول تاریخچه پرتاب تاس‌ها
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS dice_history (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            dice_value INT,
            rolled_at VARCHAR(50)
        );
        """)

        # ۴. جدول لاگ منابع امتیازگیری
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS score_logs (
            telegram_id BIGINT,
            game_type VARCHAR(100),
            count INT DEFAULT 0,
            PRIMARY KEY (telegram_id, game_type)
        );
        """)

        # ۵. جدول بازارچه لقب‌ها (Shop)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shop (
            id SERIAL PRIMARY KEY,
            title_name VARCHAR(255) UNIQUE,
            cost INT,
            category VARCHAR(50)
        );
        """)

        # ۶. جدول کدهای هدیه (Redeem Codes)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS redeem_codes (
            code VARCHAR(255) PRIMARY KEY,
            title_name VARCHAR(255),
            max_uses INT,
            current_uses INT DEFAULT 0,
            duration_hours INT
        );
        """)

        # ۷. جدول تاریخچه استفاده از کدهای هدیه
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS redeem_history (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            code VARCHAR(255),
            used_at VARCHAR(50)
        );
        """)

        # ۸. جدول سیستم مدیریت رویدادها
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_event (
            id SERIAL PRIMARY KEY,
            event_id INT,
            event_name VARCHAR(255),
            end_time VARCHAR(50),
            extra_data TEXT,
            reward_type VARCHAR(50),
            reward_value VARCHAR(255)
        );
        """)

        # ۹. جدول ویترین لقب‌های آنلاک شده هر کاربر (جدید)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_unlocked_titles (
            telegram_id BIGINT,
            title_name VARCHAR(255),
            PRIMARY KEY (telegram_id, title_name)
        );
        """)

        # ۱۰. جدول اینونتوری آیتم‌های ویژه شاپ (جدید)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_inventory (
            telegram_id BIGINT,
            item_type VARCHAR(100),
            quantity INT DEFAULT 0,
            PRIMARY KEY (telegram_id, item_type)
        );
        """)

        # ۱۱. جدول دوعل‌های غیابی لینک اختصاصی (جدید)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS offline_challenges (
            challenge_id VARCHAR(100) PRIMARY KEY,
            p1_id BIGINT,
            rounds INT,
            wager INT,
            status VARCHAR(50) DEFAULT 'pending',
            created_at VARCHAR(50)
        );
        """)

        # افزودن ادمین اولیه پروژه‌ در صورت عدم وجود
        cursor.execute("INSERT INTO admins (telegram_id) VALUES (%s) ON CONFLICT (telegram_id) DO NOTHING;", (initial_admin_id,))
        
        # پر کردن شاپ اولیه به صورت پیش‌فرض
        cursor.execute("SELECT COUNT(*) FROM shop;")
        shop_check = cursor.fetchone()[0]
        if shop_check == 0:
            default_items = [
                ('🥈 نوچه کلوب', 200, 'normal'),
                ('🥈 تاس باز', 400, 'normal'),
                ('🔮 شکارچی سایه', 1500, 'epic'),
                ('🔮 مبارز ابدی', 2500, 'epic'),
                ('👑 شاهزاده نبرد', 6000, 'legendary'),
                ('👑 گلادیاتور اعظم', 9000, 'legendary')
            ]
            for item in default_items:
                cursor.execute("INSERT INTO shop (title_name, cost, category) VALUES (%s, %s, %s) ON CONFLICT (title_name) DO NOTHING;", item)

        conn.commit()
        cursor.close()
        conn.close()
        print("✅ دیتابیس PostgreSQL ریل‌وی با موفقیت ست‌آپ شد!")
    except Exception as e:
        print(f"❌ خطا در ساخت جدول‌های پستگرس: {e}")

# اجرای راه‌اندازی دیتابیس
init_db(INITIAL_ADMIN_ID)

# ==========================================
# توابع هسته دیتابیس (نسخه PostgreSQL کاملاً بهینه)
# ==========================================

def check_and_remove_expired_titles(telegram_id):
    """بررسی و حذف لقب‌های زمانی منقضی شده قبل از هر اکشن"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT title_expire, title FROM users WHERE telegram_id = %s", (telegram_id,))
        user = cursor.fetchone()
        
        if user and user['title_expire']:
            expire_time = datetime.strptime(user['title_expire'], "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expire_time:
                cursor.execute("UPDATE users SET title = 'بدون لقب', title_expire = NULL WHERE telegram_id = %s", (telegram_id,))
                conn.commit()
                cursor.close()
                conn.close()
                return True
        cursor.close()
        conn.close()
    except Exception:
        pass
    return False

def is_user_admin(telegram_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM admins WHERE telegram_id = %s", (telegram_id,))
    admin = cursor.fetchone()
    cursor.close()
    conn.close()
    return admin is not None

def get_or_create_user(telegram_id, username):
    check_and_remove_expired_titles(telegram_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
    user = cursor.fetchone()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if not user:
        cursor.execute("""
            INSERT INTO users (telegram_id, username, score, rank, created_at, last_seen)
            VALUES (%s, %s, 0, '🥉 Bronze I', %s, %s)
        """, (telegram_id, username, now_str, now_str))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
        user = cursor.fetchone()
        # آنلاک کردن تگ اولیه پیش‌فرض
        cursor.execute("INSERT INTO user_unlocked_titles (telegram_id, title_name) VALUES (%s, 'بدون لقب') ON CONFLICT DO NOTHING;", (telegram_id,))
        conn.commit()
    else:
        cursor.execute("UPDATE users SET username = %s, last_seen = %s WHERE telegram_id = %s", (username, now_str, telegram_id))
        conn.commit()
        
    cursor.close()
    conn.close()
    return user

def calculate_rank(score, telegram_id=None):
    """محاسبه دقیق رنکینگ هاردکور کلوب تا سقف ۱۴,۰۰۰ امتیاز همراه با رنک لیدربرد Infinity"""
    if score < 0: return "💀 کفتار کلوب"
    elif score < 200: return "🥉 Bronze I"
    elif score < 600: return "🥉 Bronze II"
    elif score < 1200: return "🥈 Silver I"
    elif score < 2000: return "🥈 Silver II"
    elif score < 3500: return "🥇 Gold I"
    elif score < 5500: return "🥇 Gold II"
    elif score < 8000: return "🔮 Diamond"
    elif score < 10000: return "👑 Gladiator"
    elif score < 14000: return "👑 Kings League (لیگ پادشاهان) 🩸"
    else:
        # بررسی شرط رنک افسانه‌ای اینفینیتی (۱۰ نفر برتر بالای ۱۴,۰۰۰ کاپ)
        if telegram_id:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT telegram_id FROM users WHERE score >= 14000 ORDER BY score DESC LIMIT 10")
            top_10_ids = [row['telegram_id'] for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            if telegram_id in top_10_ids:
                return "👑 Infinity [GOD OF DICE]"
        return "👑 Legend"

def update_stats(telegram_id, score_change, mode='win'):
    """به‌روزرسانی آمار جنگی با اعمال قوانین جهنمی لیگ پادشاهان"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT score, rank, wins, losses, draws, total_games FROM users WHERE telegram_id = %s", (telegram_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.close()
        conn.close()
        return None

    # اعمال قانون جهنمی لیگ پادشاهان (بین ۱۰,۰۰۰ تا ۱۴,۰۰۰ امتیاز)
    if 10000 <= user['score'] < 14000:
        if mode == 'win':
            score_change = 80
        elif mode == 'loss':
            score_change = -100

    new_score = max(0, user['score'] + score_change)
    new_rank = calculate_rank(new_score, telegram_id)
    rank_changed = (new_rank != user['rank']) 
    
    w, l, d = user['wins'], user['losses'], user['draws']
    if mode == 'win': w += 1
    elif mode == 'loss': l += 1
    elif mode == 'draw': d += 1
    total = w + l + d
    
    cursor.execute("""
        UPDATE users 
        SET score = %s, rank = %s, wins = %s, losses = %s, draws = %s, total_games = %s
        WHERE telegram_id = %s
    """, (new_score, new_rank, w, l, d, total, telegram_id))
    
    conn.commit()
    cursor.close()
    conn.close()
    return {"new_score": new_score, "new_rank": new_rank, "rank_changed": rank_changed}

def get_top_players(limit=10):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY score DESC LIMIT %s", (limit,))
    players = cursor.fetchall()
    cursor.close()
    conn.close()
    return players 

# ==========================================
# سیستم اینونتوری و تگ‌های آنلاک شده (جدید)
# ==========================================
def get_user_inventory(telegram_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT item_type, quantity FROM user_inventory WHERE telegram_id = %s", (telegram_id,))
    inv = {row['item_type']: row['quantity'] for row in cursor.fetchall()}
    cursor.close()
    conn.close()
    return inv

def add_item_inventory(telegram_id, item_type, qty=1):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_inventory (telegram_id, item_type, quantity) VALUES (%s, %s, %s)
        ON CONFLICT (telegram_id, item_type) DO UPDATE SET quantity = user_inventory.quantity + %s
    """, (telegram_id, item_type, qty, qty))
    conn.commit()
    cursor.close()
    conn.close()

def consume_item_inventory(telegram_id, item_type):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE user_inventory SET quantity = quantity - 1 WHERE telegram_id = %s AND item_type = %s AND quantity > 0", (telegram_id, item_type))
    conn.commit()
    cursor.close()
    conn.close()

def unlock_user_title(telegram_id, title_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO user_unlocked_titles (telegram_id, title_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (telegram_id, title_name))
    conn.commit()
    cursor.close()
    conn.close()

def get_user_unlocked_titles_list(telegram_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT title_name FROM user_unlocked_titles WHERE telegram_id = %s", (telegram_id,))
    titles = [r['title_name'] for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return titles

# ==========================================
# تنظیمات کلماتی، بصری و مکانیزم‌های بازی
# ==========================================
🎰 = None
DICE_SCORES = {1: -5, 2: 5, 3: 10, 4: 15, 5: 25, 6: 40}
CAT_NAMES = {"normal": "لقب عادی", "epic": "لقب افسانه‌ای", "legendary": "لقب لجندری", "special": "آیتم ویژه شاپ"}

DICE_MOTIVATIONS = {
    6: ["🔥 **شــــــــــش ملوووووووک! میدان نبرد به آتش کشیده شد!**", "😎 شش چرخ روزگار به کامت چرخید! فوق‌العاده بود!"],
    5: ["⚡ **بسیار عالی! شانس با تو همراهه جنگجو!**", "💪 یک پرتاب قدرتمند و بی‌نقص!"],
    4: ["👍 **خوب و مطمئن! قدم به قدم به پیروزی نزدیک‌تر میشی.**", "🛡️ پرتابی محکم برای حفظ موقعیت!"],
    3: ["😐 **معمولی و متوسط... می‌تونست خیلی بهتر باشه!**", "💫 ششانس وسط زمین ایستاده، پرتاب بعدی رو محکم‌تر بزن!"],
    2: ["🤏 **امتیاز کمی بود! بوی بدشانسی میاد...**", "🌪️ تاس موافقی نبود، ولی غمت نباشه جنگجو!"],
    1: ["💀 **تاس کفتار گریبان‌گیرت شد! سقوط آزاد امتیاز!**", "❌ تاس کفتار تمام نقشه‌هات رو نقش بر آب کرد!"]
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

SPECIAL_ITEMS_LIST = {
    "item_unlimited_duel": {"name": "🔊 دوعل بدون محدودیت راند (تا ۲۰ راند)", "cost": 500},
    "item_high_wager": {"name": "💰 جواز شرط‌بندی سنگین (تا سقف ۵۰۰ امتیاز)", "cost": 800},
    "item_lucky_dice": {"name": "🔄 تاس شانس (پرتاب مجدد خودکار تاس ۱ در دوعل)", "cost": 300}
}

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
            await update.message.reply_markdown(f"💀 **وضعیت سکوت!**\nکاربر @{update.effective_user.username} به دلیل پرتاب متوالی ۱۰ تاس، به مدت **۲ دقیقه** از بازی محروم شد!")
            return False
    elif action_type == "duel":
        USER_DUEL_COUNT[user_id] = USER_DUEL_COUNT.get(user_id, 0) + 1
        USER_DICE_COUNT[user_id] = 0
        if USER_DUEL_COUNT[user_id] >= 10:
            USER_MUTE_TIMEOUT[user_id] = now + 120
            await update.message.reply_markdown(f"💀 **وضعیت سکوت دوئل!**\nکاربر @{update.effective_user.username} به دلیل ارسال ۱۰ درخواست دوئل رگباری، به مدت **۲ دقیقه** در لیست سیاه قرار گرفت!")
            return False
    return True

def get_current_active_event():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM active_event ORDER BY id DESC LIMIT 1")
        ev = cursor.fetchone()
        if not ev:
            cursor.close(); conn.close(); return None
        
        end_time = datetime.strptime(ev['end_time'], "%Y-%m-%d %H:%M:%S")
        if datetime.now() > end_time:
            cursor.execute("DELETE FROM active_event")
            conn.commit()
            cursor.close(); conn.close(); return None
        cursor.close(); conn.close()
        return ev
    except Exception:
        return None

# ==========================================
# هندلرهای اصلی فرامین ربات
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username if user.username else user.first_name)
    
    # بررسی سیستم دیپ‌لینک چلنج غیابی (Feature 1)
    if context.args and context.args[0].startswith("duel-"):
        challenge_id = context.args[0].replace("duel-", "")
        await handle_offline_link_challenge_join(update, context, challenge_id)
        return

    welcome_text = (
        f"⚔️ **به قلمرو خونین و بی‌رحم «نبرد تاس» خوش آمدی، {user.first_name}!** ⚔️\n\n"
        f"اینجا کلوپ گلادیاتورهاست؛ جایی که شانس فقط به شجاع‌ها رو می‌کنه! 🔥\n"
        f"زیرساخت ربات به دیتابیس عظیم PostgreSQL متصل شده و رنکینگ هاردکور فعال است!"
    )
    ev = get_current_active_event()
    text_btn = "🕹️ بخش ایونت (فعال 🔥)" if ev else "🕹️ بخش ایونت"
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(text_btn, callback_data="user_check_event")]])
    
    await update.message.reply_markdown(welcome_text, reply_markup=get_main_menu_keyboard())
    await update.message.reply_text("✨ جهت بررسی رویدادها و چالش‌های زنده کلوب دکمه زیر را لمس کنید:", reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "⚔️ 🔴 **لیست فرمان‌های نبرد کلوب تاس (آپدیت بزرگ هاردکور)** 🔴 ⚔️\n\n"
        "🎲 `🎲 پرتاب تاس` — پرتاب تاس انفرادی با شانس حمله بحرانی\n"
        "⚔️ `/duel [راند] [مقدار شرط]` — دوئل شرطی در گروه (سقف پیش‌فرض ۵۰ امتیاز)\n"
        "🔗 `/link_duel [راند] [مقدار شرط]` — **دوعل غیابی (لینک دعوت اختصاصی پیوی)** 🆕\n"
        "🏪 `🏪 بازارچه لقب` — خرید انواع لقب‌ها و آیتم‌های ویژه شاپ\n"
        "👤 `👤 پروفایل من` — نمایش کارنامه جنگی و منوی **انتخاب لقب**\n"
        "🏆 `🏆 تالار افتخارات` — جدول مشاهیر و ۱۰ گلادیاتور اینفینیتی\n"
        "🔑 `/redeem [کد]` — فعال‌سازی کدهای هدیه و لقب‌های موقت\n"
    )
    if is_user_admin(update.effective_user.id): help_text += "\n⚙️ `/admin` — کنترل پنل فوق پیشرفته اتاق فرماندهی"
    await update.message.reply_markdown(help_text, reply_markup=get_main_menu_keyboard())

# ==========================================
# سیستم مدیریت پرتاب‌ها و حمله بحرانی
# ==========================================
def register_and_check_critical(telegram_id, current_dice):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO dice_history (telegram_id, dice_value, rolled_at) VALUES (%s, %s, %s)", (telegram_id, current_dice, now_str))
    
    cursor.execute('SELECT dice_value FROM dice_history WHERE telegram_id = %s ORDER BY id DESC LIMIT 3', (telegram_id,))
    history = cursor.fetchall()
    
    is_critical = False
    if len(history) == 3:
        if history[0]['dice_value'] == history[1]['dice_value'] == history[2]['dice_value']:
            is_critical = True
            cursor.execute("DELETE FROM dice_history WHERE telegram_id = %s", (telegram_id,))
            
    conn.commit(); cursor.close(); conn.close()
    return is_critical

def log_score_source(telegram_id, game_type):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO score_logs (telegram_id, game_type, count) VALUES (%s, %s, 1)
        ON CONFLICT(telegram_id, game_type) DO UPDATE SET count = score_logs.count + 1
    """, (telegram_id, game_type))
    conn.commit(); cursor.close(); conn.close()

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam_and_mute(update, "dice"): return
    user_id = update.effective_user.id
    user_data = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    title_tag = f" [{user_data['title']}]" if user_data['title'] != 'بدون لقب' else ""
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
            if dice_value == 1: base_score = 40
            elif dice_value == 6: base_score = -10
            ev_bonus_text = "\n🃏 **[ایونت تاس معکوس فعال است! قوانین جابه‌جا شده‌اند]**"

    is_critical = register_and_check_critical(user_id, dice_value)
    if is_critical:
        score_gained = (dice_value * 3) * 3 if not ev or ev['event_id'] != 1 else ((dice_value * 3) * 3) * 2
        motivation = f"⚡💥 **CRITICAL HIT! حمله بحرانی رخ داد!!!** 💥⚡\nسه پرتاب متوالی روی عدد 〖 **{dice_value}** 〗 نشاندید! قدرت امتیاز شما ۳ برابر ارتقا یافت!"
    else:
        score_gained = base_score
        motivation = random.choice(DICE_MOTIVATIONS[dice_value])
    
    mode_str = 'win' if score_gained > 0 else 'loss'
    result = update_stats(user_id, score_gained, mode_str)
    log_score_source(user_id, "solo_roll")
    
    sign = "+" if score_gained >= 0 else ""
    response = (
        f"👤 **مبارز:** {user_data['username']}{title_tag}\n"
        f"🎲 **تاس:** 〖 **{dice_value}** 〗\n"
        f"📢 {motivation}\n"
        f"🏆 **تغییرات امتیاز:** {sign}{score_gained} XP{ev_bonus_text}"
    )
    if result and result["rank_changed"]: response += f"\n🎖️ **تغییر رتبه به: {result['new_rank']}**"
    await update.message.reply_markdown(response, reply_markup=get_main_menu_keyboard())

# ==========================================
# سیستم دوئل گروهی و اعمال ویژگی‌های جدید
# ==========================================
async def duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam_and_mute(update, "duel"): return
    p1 = update.effective_user
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ برای شروع دوئل گروهی، باید این دستور را روی پیام حریف ریپلای کنید!")
        return

    p2 = update.message.reply_to_message.from_user
    now = datetime.now().timestamp()
    if p1.id in DUEL_COOLDOWNS and now < DUEL_COOLDOWNS[p1.id]:
        left = int(DUEL_COOLDOWNS[p1.id] - now)
        await update.message.reply_text(f"⏳ تا {left} ثانیه دیگر نمی‌توانی دوئل جدیدی استارت کنی.")
        return

    p2_msg_id = update.message.reply_to_message.message_id
    p1_msg_id = update.message.message_id
    if p1.id == p2.id or p2.is_bot: return

    p1_inv = get_user_inventory(p1.id)
    rounds = 3
    wager = 0
    
    if context.args:
        try:
            rounds = int(context.args[0])
            if rounds < 1: rounds = 3
            # بررسی پرک سقف راندها (Feature 2)
            max_r = 20 if p1_inv.get("item_unlimited_duel", 0) > 0 else 6
            if rounds > max_r:
                rounds = max_r
                if max_r == 6:
                    await update.message.reply_text("🔊 برای استارت دوعل تا ۲۰ راند، باید آیتم ویژه «دوعل بدون محدودیت راند» را از شاپ بخرید!")
        except ValueError: pass
        
        if len(context.args) > 1:
            try:
                wager = int(context.args[1])
                if wager < 0: wager = 0
                # بررسی پرک سقف شرط‌بندی (Feature 2)
                max_w = 500 if p1_inv.get("item_high_wager", 0) > 0 else 50
                if wager > max_w:
                    wager = max_w
                    if max_w == 50:
                        await update.message.reply_text("❌ سقف شرط‌بندی عادی ۵۰ امتیاز است. جهت افزایش سقف تا ۵۰۰ امتیاز، آیتم ویژه «جواز شرط‌بندی سنگین» را تهیه کنید!")
                        return
            except ValueError: pass

    p1_name = p1.username if p1.username else p1.first_name
    p2_name = p2.username if p2.username else p2.first_name

    p1_data = get_or_create_user(p1.id, p1_name)
    p2_data = get_or_create_user(p2.id, p2_name)

    if wager > 0:
        if p1_data['score'] < wager or p2_data['score'] < wager:
            await update.message.reply_text("❌ امتیاز یکی از طرفین برای این شرط‌بندی کافی نیست!")
            return

    wager_text = f"💰 **شرط نبرد:** {wager} XP (مجموعاً {wager * 2} امتیاز در وسط زمین!)\n" if wager > 0 else ""
    keyboard = [[
        InlineKeyboardButton("⚔️ قبول می‌کنم", callback_data=f"gduel_yes_{p1.id}_{p2.id}_{rounds}_{p1_msg_id}_{p2_msg_id}_{wager}"),
        InlineKeyboardButton("🏳️ نه", callback_data=f"gduel_no_{p2.id}")
    ]]
    await update.message.reply_markdown(
        f"⚔️ **درخواست دوئل گروهی!**\n\n👤 **شروع‌کننده:** {p1_name}\n🎯 **حریف:** {p2_name}\n🏁 **راند:** {rounds}\n{wager_text}\nآیا چالش را قبول می‌کنی؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==========================================
# سیستم دوعل غیابی - لینک اختصاصی (Feature 1)
# ==========================================
async def link_duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("❌ این دستور فقط در پیوی ربات برای تولید لینک اختصاصی کار می‌کند!")
        return
    
    user_id = update.effective_user.id
    user_inv = get_user_inventory(user_id)
    user_data = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    rounds = 3
    wager = 0
    if context.args:
        try:
            rounds = int(context.args[0])
            max_r = 20 if user_inv.get("item_unlimited_duel", 0) > 0 else 6
            if rounds > max_r: rounds = max_r
        except ValueError: pass
        if len(context.args) > 1:
            try:
                wager = int(context.args[1])
                max_w = 500 if user_inv.get("item_high_wager", 0) > 0 else 50
                if wager > max_w: wager = max_w
            except ValueError: pass

    if user_data['score'] < wager:
        await update.message.reply_text("❌ امتیاز شما برای این شرط‌بندی کافی نیست!")
        return

    challenge_id = f"{user_id}x{int(datetime.now().timestamp())}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO offline_challenges (challenge_id, p1_id, rounds, wager, status, created_at)
        VALUES (%s, %s, %s, %s, 'pending', %s)
    """, (challenge_id, user_id, rounds, wager, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    cursor.close()
    conn.close()

    bot_obj = await context.bot.get_me()
    invite_link = f"https://t.me/{bot_obj.username}?start=duel-{challenge_id}"
    
    response = (
        f"🔗 **لینک چالش اختصاصی غیابی تولید شد!**\n\n"
        f"🏁 **تعداد راند:** {rounds}\n"
        f"💰 **شرط چالش:** {wager} XP\n\n"
        f"این لینک را برای حریف مدنظر خود بفرستید. حریف هر زمان وارد لینک شود و استارت بزند، بازی به صورت خودکار برگزار خواهد شد:\n"
        f"`{invite_link}`"
    )
    await update.message.reply_markdown(response)

async def handle_offline_link_challenge_join(update: Update, context: ContextTypes.DEFAULT_TYPE, challenge_id: str):
    p2 = update.effective_user
    p2_data = get_or_create_user(p2.id, p2.username if p2.username else p2.first_name)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM offline_challenges WHERE challenge_id = %s", (challenge_id,))
    challenge = cursor.fetchone()
    
    if not challenge or challenge['status'] != 'pending':
        await update.message.reply_text("❌ این لینک چالش منقضی شده یا وجود ندارد.")
        cursor.close(); conn.close(); return

    p1_id = challenge['p1_id']
    if p1_id == p2.id:
        await update.message.reply_text("❌ شما نمی‌توانید چالش لینک خودتان را قبول کنید!")
        cursor.close(); conn.close(); return

    cursor.execute("SELECT score, username FROM users WHERE telegram_id = %s", (p1_id,))
    p1_data = cursor.fetchone()
    wager = challenge['wager']

    if p1_data['score'] < wager:
        await update.message.reply_text("❌ شروع‌کننده چالش دیگر امتیاز کافی برای انجام مسابقه ندارد.")
        cursor.close(); conn.close(); return
    if p2_data['score'] < wager:
        await update.message.reply_text(f"❌ شما امتیاز کافی ندارید! امتیاز مورد نیاز: {wager} XP")
        cursor.close(); conn.close(); return

    cursor.execute("UPDATE offline_challenges SET status = 'completed' WHERE challenge_id = %s", (challenge_id,))
    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text("⚔️ **درخواست چالش غیابی تایید شد! تاس‌ریزی طرفین آغاز شد...**")
    
    p1_total, p2_total = 0, 0
    rounds = challenge['rounds']
    p1_inv = get_user_inventory(p1_id)
    p2_inv = get_user_inventory(p2.id)

    # شبیه‌سازی تاس‌ریزی و اعمال پرک تاس شانس (Feature 2 & 3)
    for _ in range(rounds):
        r1 = random.randint(1, 6)
        if r1 == 1 and p1_data['score'] < 10000 and p1_inv.get("item_lucky_dice", 0) > 0:
            consume_item_inventory(p1_id, "item_lucky_dice")
            r1 = random.randint(1, 6)
        p1_total += r1

        r2 = random.randint(1, 6)
        if r2 == 1 and p2_data['score'] < 10000 and p2_inv.get("item_lucky_dice", 0) > 0:
            consume_item_inventory(p2.id, "item_lucky_dice")
            r2 = random.randint(1, 6)
        p2_total += r2

    win_xp, lose_xp = 40, 5
    result_text = f"🏁 **نتیجه چالش غیابی (لینکی):**\n\n👤 {p1_data['username']}: {p1_total} امتیاز\n👤 {p2_data['username']}: {p2_total} امتیاز\n\n"

    if p1_total > p2_total:
        total_win = win_xp + wager
        total_lose = lose_xp - wager
        result_text += f"🏆 برنده: {p1_data['username']} (+{total_win} XP)"
        update_stats(p1_id, total_win, 'win')
        update_stats(p2.id, total_lose, 'loss')
    elif p2_total > p1_total:
        total_win = win_xp + wager
        total_lose = lose_xp - wager
        result_text += f"🏆 برنده: {p2_data['username']} (+{total_win} XP)"
        update_stats(p2.id, total_win, 'win')
        update_stats(p1_id, total_lose, 'loss')
    else:
        result_text += "🤝 چالش غیابی مساوی شد و امتیازی کسر نگردید."
        update_stats(p1_id, 0, 'draw')
        update_stats(p2.id, 0, 'draw')

    await update.message.reply_markdown(result_text)
    try:
        await context.bot.send_message(chat_id=p1_id, text=f"🔔 **یک نفر لینک چالش غیابی شما را استارت زد!**\n\n{result_text}", parse_mode="Markdown")
    except: pass

# ==========================================
# سیستم تاپ پلیرها و هندل کالبک‌ها
# ==========================================
async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_players = get_top_players()
    if not top_players:
        if update.message: await update.message.reply_text("📊 تالار افتخارات خالی است.")
        return "📊 تالار افتخارات خالی است.", []
    
    leaderboard_text = "🏆 **تالار مشاهیر و ۱۰ گلادیاتور برتر کلوب** 🏆\n\n"
    for index, player in enumerate(top_players):
        medals = "👑" if index == 0 else "⚡" if index == 1 else "🛡️" if index == 2 else "🎖️"
        title_tag = f" ({player['title']})" if player['title'] != 'بدون لقب' else ""
        leaderboard_text += f"{medals} {index + 1}. **{player['username']}**{title_tag}\n  Rank: {player['rank']} | ⭐ {player['score']} XP\n\n"
    
    leaderboard_text += "📢 *رنک‌های بالای ۱۴,۰۰۰ کاپ، لیگ اینفینیتی را تشکیل می‌دهند!*"
    keyboard = [[InlineKeyboardButton("⚔️ دوئل با برترین‌ها (مخصوص پیوی)", callback_data="pv_duel_start")]]
    
    if update.message:
        await update.message.reply_markdown(leaderboard_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return leaderboard_text, keyboard

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    if query.data == "user_check_event":
        ev = get_current_active_event()
        if not ev:
            await query.answer("❌ در حال حاضر هیچ ایونتی فعال نیست.", show_alert=True); return
        await query.answer()
        end_time = datetime.strptime(ev['end_time'], "%Y-%m-%d %H:%M:%S")
        rem = end_time - datetime.now()
        
        text = (
            f"🕹️ **پنجره اطلاعات ایونت زنده کلوب** 🕹️\n\n"
            f"🔥 **نام رویداد:** {ev['event_name']}\n"
            f"🎁 **پاداش:** {ev['reward_value'] if ev['reward_type'] != 'none' else 'جوایز سیستمی'}\n"
            f"⏳ **زمان باقی‌مانده:** {rem.seconds // 3600} ساعت"
        )
        await query.message.reply_text(text, parse_mode="Markdown")
        return

    if query.data == "pv_duel_start":
        if query.message.chat.type != "private":
            await query.answer("❌ فقط در پیوی!", show_alert=True); return
        await query.answer()
        PV_DUEL_STATES[user_id] = "WAITING_FOR_TARGET_NUMBER"
        await query.message.reply_text("🎯 لطفاً شماره بازیکن مورد نظر خود را از لیست بالا وارد کنید (مثلاً عدد 1):")
        return

    if data[0] == "pvduel" and data[1] == "yes":
        p1_id, p2_id = int(data[2]), int(data[3])
        if user_id != p2_id: await query.answer("❌ مال شما نیست!", show_alert=True); return
        await query.answer(); await query.edit_message_text("⚔️ **دوئل آغاز شد! در حال پرتاب تاس‌ها...**")
        
        p1_total, p2_total = 0, 0
        p1_inv, p2_inv = get_user_inventory(p1_id), get_user_inventory(p2_id)
        p1_m = get_or_create_user(p1_id, "Player1")
        p2_m = get_or_create_user(p2_id, "Player2")

        for _ in range(3):
            r1 = random.randint(1, 6)
            if r1 == 1 and p1_m['score'] < 10000 and p1_inv.get("item_lucky_dice", 0) > 0:
                consume_item_inventory(p1_id, "item_lucky_dice")
                r1 = random.randint(1, 6)
            p1_total += r1
            
            r2 = random.randint(1, 6)
            if r2 == 1 and p2_m['score'] < 10000 and p2_inv.get("item_lucky_dice", 0) > 0:
                consume_item_inventory(p2_id, "item_lucky_dice")
                r2 = random.randint(1, 6)
            p2_total += r2

        win_xp, lose_xp = 40, 5
        res_p1 = f"📊 نتیجه: تو {p1_total} - حریف {p2_total}\n"
        if p1_total > p2_total:
            res_p1 += f"🏆 پیروز شدید! (+{win_xp} XP)"; update_stats(p1_id, win_xp, 'win'); update_stats(p2_id, lose_xp, 'loss')
        elif p2_total > p1_total:
            res_p1 += f"💀 شکست خوردید! (+{lose_xp} XP)"; update_stats(p2_id, win_xp, 'win'); update_stats(p1_id, lose_xp, 'loss')
        else:
            res_p1 += "🤝 مساوی شد!"; update_stats(p1_id, 0, 'draw'); update_stats(p2_id, 0, 'draw')
            
        try: await context.bot.send_message(chat_id=p1_id, text=res_p1)
        except: pass
        try: await context.bot.send_message(chat_id=p2_id, text=res_p1)
        except: pass
        return

    if data[0] == "gduel" and data[1] == "yes":
        p1_id, p2_id, rounds = int(data[2]), int(data[3]), int(data[4])
        p1_msg_id, p2_msg_id = int(data[5]), int(data[6])
        wager = int(data[7])
        
        if user_id != p2_id: 
            await query.answer("❌ این چالش برای شما نیست!", show_alert=True); return
        
        p1_chk = get_or_create_user(p1_id, "P1")
        p2_chk = get_or_create_user(p2_id, "P2")
        if p1_chk['score'] < wager or p2_chk['score'] < wager:
            await query.answer("❌ امتیازات ناگهان کم شده است!", show_alert=True); return
            
        await query.answer(); await query.edit_message_text("⚔️ **نبرد گروهی تایید شد! بازی شروع می‌شود...**")
        
        p1_total, p2_total = 0, 0
        p1_inv = get_user_inventory(p1_id)
        p2_inv = get_user_inventory(p2_id)

        await context.bot.send_message(chat_id=chat_id, text=f"🎲 **انداختن تاس برای بازیکن اول...**")
        for _ in range(rounds):
            d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p1_msg_id)
            rv = d.dice.value
            if rv == 1 and p1_chk['score'] < 10000 and p1_inv.get("item_lucky_dice", 0) > 0:
                consume_item_inventory(p1_id, "item_lucky_dice")
                await context.bot.send_message(chat_id=chat_id, text="🔄 پرک تاس شانس فعال شد! ری-رول خودکار...")
                d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p1_msg_id)
                rv = d.dice.value
            p1_total += rv
            await asyncio.sleep(2.5)

        await context.bot.send_message(chat_id=chat_id, text=f"🎲 **انداختن تاس برای بازیکن دوم...**")
        for _ in range(rounds):
            d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p2_msg_id)
            rv = d.dice.value
            if rv == 1 and p2_chk['score'] < 10000 and p2_inv.get("item_lucky_dice", 0) > 0:
                consume_item_inventory(p2_id, "item_lucky_dice")
                await context.bot.send_message(chat_id=chat_id, text="🔄 پرک تاس شانس فعال شد! ری-رول خودکار...")
                d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p2_msg_id)
                rv = d.dice.value
            p2_total += rv
            await asyncio.sleep(2.5)

        win_xp, lose_xp = 40, 5
        result_text = f"🏁 **نتیجه مسابقه:**\n\n👤 بازیکن اول: {p1_total}\n👤 بازیکن دوم: {p2_total}\n\n"
        
        if p1_total > p2_total:
            result_text += f"🏆 برنده مسابقه با احتساب شرط: (+{win_xp + wager} XP)"
            update_stats(p1_id, win_xp + wager, 'win'); update_stats(p2_id, lose_xp - wager, 'loss')
        elif p2_total > p1_total:
            result_text += f"🏆 برنده مسابقه با احتساب شرط: (+{win_xp + wager} XP)"
            update_stats(p2_id, win_xp + wager, 'win'); update_stats(p1_id, lose_xp - wager, 'loss')
        else:
            result_text += "🤝 مساوی!"
            update_stats(p1_id, 0, 'draw'); update_stats(p2_id, 0, 'draw')
            
        await context.bot.send_message(chat_id=chat_id, text=result_text)
        return

    # مدیریت منوی جدید انتخاب لقب (Feature 4)
    if query.data == "select_title_root":
        await query.answer()
        titles = get_user_unlocked_titles_list(user_id)
        kb = []
        for t in titles:
            kb.append([InlineKeyboardButton(f"✨ لقب: {t}", callback_data=f"setactive_{t}")])
        kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_close")])
        await query.edit_message_text("👑 **ویترین انتخاب لقب‌های شما:**\nلقب مدنظر را جهت نمایش انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data[0] == "setactive":
        title_name = query.data.replace("setactive_", "")
        await query.answer()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET title = %s WHERE telegram_id = %s", (title_name, user_id))
        conn.commit()
        cursor.close(); conn.close()
        await query.edit_message_text(f"✅ لقب پروفایل شما با موفقیت به « **{title_name}** » تغییر یافت!")
        return

    if data[0] == "admin": await admin_buttons(update, context)
    if data[0] == "shop": await shop_callback(update, context)

# ==========================================
# سیستم مانیتورینگ متون و اتصال دکمه‌ها
# ==========================================
async def monitor_messages_and_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # الگوریتم بک‌آپ‌گیری ادمین بوسیله کپی تالار مشاهیر
    if is_user_admin(user_id) and ("تالار مشاهیر" in text or "۱۰ گلادیاتور برتر" in text) and "XP" in text:
        lines = text.split("\n"); current_username = None; updated_count = 0
        conn = get_db_connection()
        cursor = conn.cursor()
        for line in lines:
            user_match = re.search(r'(?:\d+\.\s*|👑|⚡|🛡️|🎖️)\s*([A-Za-z0-9_]+)', line)
            if user_match: current_username = user_match.group(1).strip()
            score_match = re.search(r'(?:⭐\s*|\b)(\d+)\s*XP', line)
            if score_match and current_username:
                score_val = int(score_match.group(1)); rank_val = calculate_rank(score_val, user_id)
                cursor.execute("SELECT 1 FROM users WHERE username = %s", (current_username,))
                user_check = cursor.fetchone()
                if user_check:
                    cursor.execute("UPDATE users SET score = %s, rank = %s WHERE username = %s", (score_val, rank_val, current_username))
                else:
                    fake_id = -random.randint(1000000, 9999999); now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute("INSERT INTO users (telegram_id, username, score, rank, created_at, last_seen) VALUES (%s, %s, %s, %s, %s, %s)",
                                   (fake_id, current_username, score_val, rank_val, now_str, now_str))
                updated_count += 1; current_username = None
        conn.commit(); cursor.close(); conn.close()
        if updated_count > 0:
            await update.message.reply_text(f"✅ آمار {updated_count} کاربر بازیابی و با موفقیت ست شد.")
            return

    p_name = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    get_or_create_user(user_id, p_name)

    if text == "🎲 پرتاب تاس": 
        await dice_command(update, context); return
    elif text == "👤 پروفایل من": 
        await profile_command(update, context); return
    elif text == "🏆 تالار افتخارات": 
        await top_command(update, context); return
    elif text == "🏪 بازارچه لقب": 
        await shop_command(update, context); return
    elif text == "ℹ️ راهنمای کلوب": 
        await help_command(update, context); return

    # ادمین استیت‌ها
    if user_id in ADMIN_STATES:
        state = ADMIN_STATES[user_id]
        if state == "WAITING_FOR_BROADCAST":
            del ADMIN_STATES[user_id]
            conn = get_db_connection(); cursor = conn.cursor()
            cursor.execute('SELECT telegram_id FROM users'); rows = cursor.fetchall(); conn.close()
            for row in rows:
                try: await context.bot.send_message(chat_id=row['telegram_id'], text=f"📢 **اطلاعیه مدیریت:**\n\n{text}", parse_mode="Markdown")
                except: continue
            await update.message.reply_text("✅ پیام فرستاده شد.")
        elif state == "WAITING_FOR_CUSTOM_USER":
            ADMIN_STATES[user_id] = f"SET_SCORE_VAL_{text.replace('@', '')}"
            await update.message.reply_text(f"🔢 مقدار امتیاز جدید:")
        elif state.startswith("SET_SCORE_VAL_"):
            target_username = state.replace("SET_SCORE_VAL_", "")
            del ADMIN_STATES[user_id]
            try: target_score = int(text)
            except ValueError: return
            new_rank = calculate_rank(target_score)
            conn = get_db_connection(); cursor = conn.cursor()
            cursor.execute("UPDATE users SET score = %s, rank = %s WHERE username = %s", (target_score, new_rank, target_username))
            conn.commit(); conn.close()
            await update.message.reply_text("🚀 اعمال شد.")
        return

# ==========================================
# سیستم فروشگاه و انتخاب لقب‌ها
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
        f"🟢 پیروزی: {user['wins']}  |  🤝 مساوی: {user['draws']}  |  🔴 شکست: {user['losses']}\n🔥 **نرخ برد:** {win_rate}%\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    # دکمه شیشه‌ای ویترین لقب‌ها (Feature 4)
    kb = [[InlineKeyboardButton("👑 انتخاب و تغییر لقب نمایش", callback_data="select_title_root")]]
    await update.message.reply_markdown(profile_text, reply_markup=InlineKeyboardMarkup(kb))

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    keyboard = [
        [InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal")],
        [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
        [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")],
        [InlineKeyboardButton("🛍️ شاپ آیتم‌های ویژه (جدید 🔥)", callback_data="shopmain_cat_special")]
    ]
    await update.message.reply_text(f"🏪 **به بازارچه فوق پیشرفته کلوب خوش آمدی!**\n💰 موجودی: {user['score']} XP\n\nدسته‌بندی را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = query.from_user.id; data = query.data
    await query.answer()
    
    if data.startswith("shopmain_cat_"):
        cat_type = data.replace("shopmain_cat_", "")
        
        # مدیریت بخش آیتم‌های ویژه (Feature 2)
        if cat_type == "special":
            keyboard = []
            for k, v in SPECIAL_ITEMS_LIST.items():
                keyboard.append([InlineKeyboardButton(f"{v['name']} - قیمت: {v['cost']} XP", callback_data=f"shopbuy_special_{k}")])
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shopmain_back")])
            await query.edit_message_text("🛍️ **لیست آیتم‌های کمکی ویژه بازارچه:**", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("SELECT id, title_name, cost FROM shop WHERE category = %s", (cat_type,))
        shop_items = cursor.fetchall(); conn.close()
        
        keyboard = []
        for item in shop_items:
            keyboard.append([InlineKeyboardButton(f"{item['title_name']} 💰 {item['cost']} XP", callback_data=f"shopbuy_id_{item['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shopmain_back")])
        await query.edit_message_text(f"🛍️ لیست لقب‌های بخش: {CAT_NAMES[cat_type]}", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "shopmain_back":
        keyboard = [
            [InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal")],
            [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
            [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")],
            [InlineKeyboardButton("🛍️ شاپ آیتم‌های ویژه (جدید 🔥)", callback_data="shopmain_cat_special")]
        ]
        await query.edit_message_text("🏪 **بازارچه لقب‌ها و آیتم‌ها**", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data.startswith("shopbuy_id_"):
        item_id = int(data.split("_")[2])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("SELECT * FROM shop WHERE id = %s", (item_id,))
        item = cursor.fetchone()
        
        user = get_or_create_user(user_id, query.from_user.username)
        if user['score'] < item['cost']:
            await context.bot.send_message(chat_id=query.message.chat_id, text="❌ امتیاز کافی نداری مشتی!"); cursor.close(); conn.close(); return
        
        new_score = user['score'] - item['cost']
        cursor.execute('UPDATE users SET score = %s, title = %s WHERE telegram_id = %s', (new_score, item['title_name'], user_id))
        conn.commit(); cursor.close(); conn.close()
        unlock_user_title(user_id, item['title_name']) # آنلاک در ویترین
        await query.edit_message_text(f"🎉 تگ ویژه « {item['title_name']} » خریداری شد و در ویترین لقب‌ها باز شد!")

    elif data.startswith("shopbuy_special_"):
        item_key = data.replace("shopbuy_special_", "")
        item_info = SPECIAL_ITEMS_LIST[item_key]
        user = get_or_create_user(user_id, query.from_user.username)
        
        if user['score'] < item_info['cost']:
            await context.bot.send_message(chat_id=query.message.chat_id, text="❌ امتیاز شما برای خرید این آیتم کافی نیست!"); return
            
        new_score = user['score'] - item_info['cost']
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("UPDATE users SET score = %s WHERE telegram_id = %s", (new_score, user_id))
        conn.commit(); cursor.close(); conn.close()
        
        add_item_inventory(user_id, item_key, 1)
        await query.edit_message_text(f"🎉 آیتم ویژه **{item_info['name']}** با موفقیت خریداری و به اینونتوری شما اضافه شد!")

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = context.args[0].strip() if context.args else ""
    if not code: return
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT * FROM redeem_codes WHERE code = %s', (code,))
    cdata = cursor.fetchone()
    if not cdata: await update.message.reply_text("❌ کد نامعتبر"); cursor.close(); conn.close(); return
    
    unlock_user_title(user_id, cdata['title_name'])
    await update.message.reply_text(f"🎉 لقب **{cdata['title_name']}** در ویترین لقب‌های شما باز شد!")
    cursor.close(); conn.close()

# ==========================================
# بخش کنترل پنل ادمین
# ==========================================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_user_admin(update.effective_user.id): return
    keyboard = [
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🚀 ارتقا امتیاز دلخواه", callback_data="admin_set_score")],
        [InlineKeyboardButton("❌ بستن پنل", callback_data="admin_close")]
    ]
    await update.message.reply_text("🛠 **اتاق فرمان مدیریت ربات:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = query.from_user.id; data = query.data
    await query.answer()
    if data == "admin_broadcast":
        ADMIN_STATES[user_id] = "WAITING_FOR_BROADCAST"
        await query.edit_message_text("📢 متن پیام همگانی خود را ارسال کنید:")
    elif data == "admin_set_score":
        ADMIN_STATES[user_id] = "WAITING_FOR_CUSTOM_USER"
        await query.edit_message_text("👤 نام کاربری فرد مورد نظر را بدون @ بفرستید:")
    elif data == "admin_close":
        await query.edit_message_text("🔒 بسته شد.")

# ==========================================
# تابع اصلی اجرا کننده (Main)
# ==========================================
def main():
    application = Application.builder().token(BOT_TOKEN).job_queue(None).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("dice", dice_command))
    application.add_handler(CommandHandler("duel", duel_command))
    application.add_handler(CommandHandler("link_duel", link_duel_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("top", top_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("shop", shop_command))
    application.add_handler(CommandHandler("redeem", redeem_command))

    application.add_handler(CallbackQueryHandler(handle_callbacks, pattern="^(pv_duel_start|pvduel_|gduel_|user_check_event|select_title_root|setactive_)"))
    application.add_handler(CallbackQueryHandler(admin_buttons, pattern="^(admin_)"))
    application.add_handler(CallbackQueryHandler(shop_callback, pattern="^(shopmain_|shopbuy_)"))
    
    async def mid_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message and update.message.text:
            uid = update.effective_user.id
            txt = update.message.text.strip()
            p_username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
            get_or_create_user(uid, p_username)
            
            if txt in ["🎲 پرتاب تاس", "👤 پروفایل من", "🏆 تالار افتخارات", "🏪 بازارچه لقب", "ℹ️ راهنمای کلوب"]:
                await monitor_messages_and_inputs(update, context); return
        await monitor_messages_and_inputs(update, context)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mid_filter))

    print("🚀 ربات نبرد تاس هاردکور با دیتابیس PostgreSQL ران شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
