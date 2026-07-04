import os
import random
import sqlite3
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

# ==========================================
# تنظیمات اصلی ربات از طریق محیط سرور (Railway Variables)
# ==========================================
# در پنل Railway دو متغیر با نام‌های BOT_TOKEN و ADMIN_ID بسازید
BOT_TOKEN = os.getenv("BOT_TOKEN", "8894117383:AAFGeDmC1lnY_LoFaah7zTAX7NjriIb2-Tc")
INITIAL_ADMIN_ID = int(os.getenv("ADMIN_ID", "7430881772"))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# مسیر دیتابیس امن و دائمی برای سرور Railway
DB_FILE = "/app/data/games.db"

# ==========================================
# ۱. راه‌اندازی دیتابیس ارتقایافته
# ==========================================
def init_db():
    # مطمئن می‌شویم پوشه دیتابیس در صورت عدم وجود ساخته شود
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    
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
    
    try: cursor.execute("ALTER TABLE users ADD COLUMN last_seen TEXT")
    except sqlite3.OperationalError: pass

    try: cursor.execute("ALTER TABLE users ADD COLUMN title TEXT DEFAULT 'بدون لقب'")
    except sqlite3.OperationalError: pass
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            telegram_id INTEGER PRIMARY KEY,
            added_at TEXT
        )
    ''')
    cursor.execute('INSERT OR IGNORE INTO admins (telegram_id, added_at) VALUES (?, ?)', 
                   (INITIAL_ADMIN_ID, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    
    conn.commit()
    conn.close()

init_db()

# ==========================================
# ۲. لیست رنک‌ها و دیتای مغازه لقب‌ها
# ==========================================
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
    {"name": "💎 Diamond I", "minScore": 3000},
    {"name": "💎 Diamond II", "minScore": 3800},
    {"name": "💎 Diamond III", "minScore": 4800},
    {"name": "👑 Master", "minScore": 6000}
]

SHOP_TITLES = {
    "t1": {"name": "💀 تاس‌انداز مرگ", "cost": 1000},
    "t2": {"name": "🔮 ارباب شانس", "cost": 1500},
    "t3": {"name": "⚔️ گلادیاتور اعظم", "cost": 2000},
    "t4": {"name": "🧛 روح تاریک نبرد", "cost": 2500},
    "t5": {"name": "🦅 ققنوس جاودان", "cost": 4000}
}

def calculate_rank(score):
    current_rank = RANKS[0]["name"]
    for rank in RANKS:
        if score >= rank["minScore"]:
            current_rank = rank["name"]
        else:
            break
    return current_rank

# ==========================================
# ۳. توابع اصلی دیتابیس
# ==========================================
def is_user_admin(telegram_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    res = cursor.execute('SELECT 1 FROM admins WHERE telegram_id = ?', (telegram_id,)).fetchone()
    conn.close()
    return res is not None

def get_or_create_user(telegram_id, username):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    clean_username = username.replace("@", "") if username else None
    
    user = cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)).fetchone()
    if not user:
        name = clean_username if clean_username else f"User_{telegram_id}"
        cursor.execute('INSERT INTO users (telegram_id, username, created_at, last_seen) VALUES (?, ?, ?, ?)', 
                       (telegram_id, name, now_str, now_str))
        conn.commit()
        user = cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)).fetchone()
    else:
        if clean_username:
            cursor.execute('UPDATE users SET last_seen = ?, username = ? WHERE telegram_id = ?', (now_str, clean_username, telegram_id))
        else:
            cursor.execute('UPDATE users SET last_seen = ? WHERE telegram_id = ?', (now_str, telegram_id))
        conn.commit()
        
    conn.close()
    return user

def update_stats(telegram_id, score_gained, is_win):
    user = get_or_create_user(telegram_id, None)
    new_score = max(0, user['score'] + score_gained)
    new_rank = calculate_rank(new_score)
    win_inc = 1 if is_win else 0
    loss_inc = 0 if is_win else 1
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET score = ?, rank = ?, wins = wins + ?, losses = losses + ?, total_games = total_games + 1, last_seen = ?
        WHERE telegram_id = ?
    ''', (new_score, new_rank, win_inc, loss_inc, now_str, telegram_id))
    conn.commit()
    conn.close()
    
    return {"old_rank": user['rank'], "new_rank": new_rank, "rank_changed": new_rank != user['rank']}

def get_top_players():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    top_users = cursor.execute('SELECT username, rank, title, score FROM users ORDER BY score DESC LIMIT 10').fetchall()
    conn.close()
    return top_users

# ==========================================
# ۴. بخش دستورات عمومی چت و بازی‌ها
# ==========================================
ACTIVE_DUELS = {}
USER_COOLDOWNS = {}
COOLDOWN_TIME = 1.5
ADMIN_STATES = {}

async def check_cooldown(update: Update) -> bool:
    if not update.message: return False
    user_id = update.effective_user.id
    now = datetime.now().timestamp()
    if user_id in USER_COOLDOWNS and now < USER_COOLDOWNS[user_id]:
        await update.message.reply_text('⚡ **آرام‌تر! چند لحظه صبر کن و بعد دستور بفرست.**')
        return False
    USER_COOLDOWNS[user_id] = now + COOLDOWN_TIME
    return True

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    user = update.effective_user
    get_or_create_user(user.id, user.username if user.username else user.first_name)
    await update.message.reply_markdown(
        f"🔥 **سلام {user.first_name}! به کلوب رسمی نبرد تاس خوش آمدی!**\n\n"
        f"اینجا جاییه که شانس و استراتژی تو رو به اوج می‌رسونه. برای دیدن فرمان‌های جنگی همین حالا دستور `/help` رو بفرست! ⚔️"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    help_text = (
        "⚔️ 🔴 **لیست فرمان‌های نبرد کلوب تاس** 🔴 ⚔️\n\n"
        "🎲 `/dice` — پرتاب تاس شانسی و دریافت امتیاز روزانه\n"
        "⚔️ `/duel [راند]` — **دوئل مرگبار!** (پیام حریفت رو ریپلای کن و این دستور رو بفرست. مثال: `/duel 3`)\n"
        "🏪 `/shop` — **بازارچه لقب‌های حماسی** (مخصوص رنک‌های Master)\n"
        "👤 `/profile` — نمایش مشخصات، رنک و کارنامه جنگی شما\n"
        "🏆 `/top` — جدول ۱۰ مبارز و گلادیاتور برتر کلوب\n"
    )
    if is_user_admin(update.effective_user.id):
        help_text += "⚙️ `/admin` — ورود به اتاق کنترل (مخصوص ادمین)"
    await update.message.reply_markdown(help_text)

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    user_id = update.effective_user.id
    user_data = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    title_tag = f" [{user_data['title']}]" if user_data['title'] != 'بدون لقب' else ""
    
    dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id)
    dice_value = dice_msg.dice.value
    await asyncio.sleep(3)
    
    score_gained, is_win, status_text = 0, False, ""
    
    if dice_value == 6: score_gained, is_win, status_text = 50, True, "🔥 **شــــــــــش ملوووووووک!** حاکم میدان شدی!"
    elif dice_value == 5: score_gained, is_win, status_text = 30, True, "😎 فوق‌العاده بود! شانس یارت هست."
    elif dice_value == 4: score_gained, is_win, status_text = 20, True, "👍 نتیجه خوب و امیدوارکننده."
    elif dice_value == 3: score_gained, is_win, status_text = 10, True, "😐 بد نبود، معمولی و گذران."
    elif dice_value == 2: score_gained, is_win, status_text = -5, False, "🤏 ای وای! شانس همراهی نکرد."
    elif dice_value == 1: score_gained, is_win, status_text = -15, False, "💀 سقوط آزاد! تاس کفتار گریبان‌گیرت شد!"
    
    result = update_stats(user_id, score_gained, is_win)
    
    response = (
        f"👤 **مبارز:** {user_data['username']}{title_tag}\n"
        f"🎲 **نتیجه پرتاب:** 〖 **{dice_value}** 〗\n"
        f"✨ **وضعیت:** {status_text}\n"
        f"🏆 **تغییرات امتیاز:** {score_gained:+} امتیاز"
    )
    if result["rank_changed"]:
        response += f"\n\n🎖️ **ارتقای رتبه!** سطح نظامی شما به **{result['new_rank']}** صعود کرد!"
        
    await update.message.reply_markdown(response)

async def duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in ACTIVE_DUELS:
        await update.message.reply_text("🚨 **یک نبرد خونین همین حالا در گروه جریان دارد! صبور باشید.**")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ برای شروع دوئل، باید این دستور را روی پیام حریف خود ریپلای کنید!")
        return

    p1, p2 = update.effective_user, update.message.reply_to_message.from_user
    if p1.id == p2.id: return
    if p2.is_bot: return

    rounds = 3
    if context.args:
        try:
            rounds = int(context.args[0])
            if rounds < 1 or rounds > 10: rounds = 3
        except ValueError: pass

    get_or_create_user(p1.id, p1.username if p1.username else p1.first_name)
    get_or_create_user(p2.id, p2.username if p2.username else p2.first_name)

    ACTIVE_DUELS[chat_id] = {
        "p1_id": p1.id, "p1_name": p1.username if p1.username else p1.first_name, "p1_score": 0,
        "p2_id": p2.id, "p2_name": p2.username if p2.username else p2.first_name, "p2_score": 0,
        "total_rounds": rounds, "current_round": 1, "waiting_for": p1.id
    }

    await update.message.reply_markdown(
        f"⚔️ **اعلام جنگ! دوئل حیثیتی آغاز شد** ⚔️\n\n"
        f"🎖️ **گلادیاتور اول:** {ACTIVE_DUELS[chat_id]['p1_name']}\n"
        f"🎖️ **گلادیاتور دوم:** {ACTIVE_DUELS[chat_id]['p2_name']}\n"
        f"🏁 **تعداد کل راندها:** {rounds}\n\n"
        f"📣 {ACTIVE_DUELS[chat_id]['p1_name']} نبرد را آغاز کن! بفرست: `/dice`"
    )

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    win_rate = round((user['wins'] / user['total_games']) * 100, 1) if user['total_games'] > 0 else 0
    title_display = f"🏅 **لقب ویژه:** {user['title']}" if user['title'] != 'بدون لقب' else "🏅 **لقب ویژه:** ندارد"
    
    profile_text = (
        f"🎮 ━━━ **کارت عضویت کلوب نبرد** ━━━ 🎮\n\n"
        f"👤 **نام جنگجو:** {user['username']}\n"
        f"{title_display}\n"
        f"👑 **رتبه فعلی:** {user['rank']}\n"
        f"💎 **کل امتیازات:** {user['score']} XP\n\n"
        f"📊 **آمار جنگ‌ها:**\n"
        f"⚔️ کل مسابقات: {user['total_games']}\n"
        f"🟢 پیروزی: {user['wins']}  |  🔴 شکست: {user['losses']}\n"
        f"🔥 **نرخ برد (WinRate):** {win_rate}%\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_markdown(profile_text)

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    top_players = get_top_players()
    if not top_players:
        await update.message.reply_text("📊 تالار افتخارات هنوز خالی است.")
        return
        
    leaderboard_text = "🏆 **تالار مشاهیر و ۱۰ گلادیاتور برتر کلوب** 🏆\n\n"
    for index, player in enumerate(top_players):
        medals = "👑" if index == 0 else "⚡" if index == 1 else "🛡️" if index == 2 else "🎖️"
        title_tag = f" ({player['title']})" if player['title'] != 'بدون لقب' else ""
        leaderboard_text += f"{medals} {index + 1}. **{player['username']}**{title_tag}\n  Rank: {player['rank']} | ⭐ {player['score']} XP\n\n"
        
    await update.message.reply_markdown(leaderboard_text)

# ==========================================
# ۵. بخش فروشگاه لقب‌های حماسی (SHOP)
# ==========================================
async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    if user['rank'] != "👑 Master":
        await update.message.reply_markdown(
            "🔒 **دسترسی محدود!**\n"
            "بازارچه لقب‌های اساطیری قفل است. شما ابتدا باید به رنک نهایی یعنی **👑 Master** برسید تا قفل بازارچه برایتان باز شود!"
        )
        return
        
    keyboard = []
    for key, item in SHOP_TITLES.items():
        keyboard.append([InlineKeyboardButton(f"{item['name']} 💰 {item['cost']} امتیاز", callback_data=f"buy_{key}")])
    
    await update.message.reply_text(
        "🏪 **به بازارچه اساطیری خوش آمدی استاد اعظم!**\n"
        "امتیاز خود را خرج خرید لقب‌های جاودان کن تا در تمام گروه ها و جدول‌ها درخشش داشته باشی:\n"
        f"💰 موجودی امتیاز شما: {user['score']} XP",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    if not data.startswith("buy_"): return
    await query.answer()
    
    title_key = data.split("_")[1]
    if title_key not in SHOP_TITLES: return
    
    item = SHOP_TITLES[title_key]
    user = get_or_create_user(user_id, query.from_user.username if query.from_user.username else query.from_user.first_name)
    
    if user['rank'] != "👑 Master": return
        
    if user['score'] < item['cost']:
        await context.bot.send_message(chat_id=user_id, text=f"❌ **موجودی امتیاز شما کافی نیست! برای خرید این لقب به {item['cost']} امتیاز نیاز دارید.**")
        return
        
    new_score = user['score'] - item['cost']
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET score = ?, title = ? WHERE telegram_id = ?', (new_score, item['name'], user_id))
    conn.commit()
    conn.close()
    
    await query.edit_message_text(f"🎉 **تبریک با شکوه! شما لقب حماسی « {item['name']} » را با موفقیت خریدید و روی اکانت شما فعال شد!**")


# ==========================================
# ۶. بخش سیستم پنل مدیریت ربات (ارتقا یافته)
# ==========================================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_user_admin(update.effective_user.id): return
    keyboard = [
        [InlineKeyboardButton("📊 لیست کاربران و امتیازات", callback_data="admin_users")],
        [InlineKeyboardButton("📢 ارسال پیام همگانی به گروه‌ها", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🚀 ارتقای آنی به رنک Master", callback_data="admin_set_master")],
        [InlineKeyboardButton("🧹 صفر کردن امتیاز کاربر", callback_data="admin_reset_score")],
        [InlineKeyboardButton("➕ افزودن ادمین جدید", callback_data="admin_add")],
        [InlineKeyboardButton("❌ بستن پنل ادمین", callback_data="admin_close")]
    ]
    await update.message.reply_text("🛠 **اتاق فرمان و پنل مدیریت کلوب:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not is_user_admin(user_id): return
    await query.answer()
    data = query.data

    if data == "admin_users":
        conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        users = cursor.execute('SELECT username, score, rank FROM users ORDER BY score DESC LIMIT 15').fetchall(); conn.close()
        txt = "📊 **لیست آمار کاربران:**\n\n"
        for idx, u in enumerate(users):
            txt += f"{idx+1}. 👤 @{u['username']} | ⭐ امتیاز: {u['score']} | {u['rank']}\n"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))

    elif data == "admin_broadcast":
        ADMIN_STATES[user_id] = "WAITING_FOR_BROADCAST"
        await query.edit_message_text("📢 متن پیام همگانی خود را ارسال کنید:")

    elif data == "admin_set_master":
        ADMIN_STATES[user_id] = "WAITING_FOR_USERNAME_MASTER"
        await query.edit_message_text("🚀 **نام کاربری (Username) فرد مورد نظر را بدون @ ارسال کنید:**\nربات او را فوراً به رنک آخر (👑 Master) با ۶۰۰۰ امتیاز ارتقا می‌دهد.")

    elif data == "admin_reset_score":
        ADMIN_STATES[user_id] = "WAITING_FOR_USERNAME_RESET"
        await query.edit_message_text("🧹 **نام کاربری (Username) فرد مورد نظر را بدون @ ارسال کنید:**\nامتیازات او کاملاً صفر شده و به رنک برنز ۱ سقوط می‌کند.")

    elif data == "admin_add":
        ADMIN_STATES[user_id] = "WAITING_FOR_ADMIN_ID"
        await query.edit_message_text("➕ آی‌دی عددی ادمین جدید را بفرستید:")

    elif data == "admin_home":
        keyboard = [
            [InlineKeyboardButton("📊 لیست کاربران و امتیازات", callback_data="admin_users")],
            [InlineKeyboardButton("📢 ارسال پیام همگانی به گروه‌ها", callback_data="admin_broadcast")],
            [InlineKeyboardButton("🚀 ارتقای آنی به رنک Master", callback_data="admin_set_master")],
            [InlineKeyboardButton("🧹 صفر کردن امتیاز کاربر", callback_data="admin_reset_score")],
            [InlineKeyboardButton("➕ افزودن ادمین جدید", callback_data="admin_add")],
            [InlineKeyboardButton("❌ بستن پنل ادمین", callback_data="admin_close")]
        ]
        await query.edit_message_text("🛠 **اتاق فرمان و پنل مدیریت کلوب:**", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "admin_close":
        await query.edit_message_text("🔒 پنل مدیریت بسته شد.")

# ==========================================
# ۷. پایشگر پیام‌ها و ورودی‌های ادمین و دوئل
# ==========================================
async def monitor_messages_and_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)

    if user_id in ADMIN_STATES:
        state = ADMIN_STATES[user_id]
        
        if state == "WAITING_FOR_BROADCAST":
            del ADMIN_STATES[user_id]
            await update.message.reply_text("⏳ در حال انتشار پیام...")
            conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
            rows = cursor.execute('SELECT telegram_id FROM users').fetchall(); conn.close()
            success = 0
            for row in rows:
                try:
                    await context.bot.send_message(chat_id=row[0], text=f"📢 **اطلاعیه جدید مدیریت:**\n\n{text}", parse_mode="Markdown")
                    success += 1
                    await asyncio.sleep(0.1)
                except Exception: continue
            await update.message.reply_text(f"✅ پیام به {success} چت فرستاده شد.")
            return
            
        elif state == "WAITING_FOR_USERNAME_MASTER":
            del ADMIN_STATES[user_id]
            target_username = text.replace("@", "")
            conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
            cursor.execute("UPDATE users SET score = 6000, rank = '👑 Master' WHERE username = ?", (target_username,))
            changes = conn.total_changes
            conn.commit(); conn.close()
            if changes > 0:
                await update.message.reply_markdown(f"🚀 کاربر @{target_username} با موفقیت به رنک نهایی **👑 Master** صعود کرد و ۶۰۰۰ امتیاز گرفت!")
            else:
                await update.message.reply_text("❌ خطا: این نام کاربری در دیتابیس ربات پیدا نشد. (باید حداقل یکبار ربات را استارت زده باشد)")
            return

        elif state == "WAITING_FOR_USERNAME_RESET":
            del ADMIN_STATES[user_id]
            target_username = text.replace("@", "")
            conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
            cursor.execute("UPDATE users SET score = 0, rank = '🥉 Bronze I', title = 'بدون لقب' WHERE username = ?", (target_username,))
            changes = conn.total_changes
            conn.commit(); conn.close()
            if changes > 0:
                await update.message.reply_markdown(f"🧹 حساب کاربری @{target_username} کاملاً پاکسازی شد! امتیاز: 0 | رنک: Bronze I")
            else:
                await update.message.reply_text("❌ خطا: این نام کاربری در دیتابیس ربات پیدا نشد.")
            return

        elif state == "WAITING_FOR_ADMIN_ID":
            del ADMIN_STATES[user_id]
            try:
                new_id = int(text)
                conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
                cursor.execute('INSERT OR IGNORE INTO admins (telegram_id, added_at) VALUES (?, ?)', (new_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit(); conn.close()
                await update.message.reply_text("✅ ادمین جدید ثبت شد.")
            except ValueError: await update.message.reply_text("❌ آیدی معتبر نیست.")
            return

    # منطق راندهای بازی دوئل تاس
    if chat_id in ACTIVE_DUELS and text == "/dice":
        duel = ACTIVE_DUELS[chat_id]
        if user_id != duel["waiting_for"]: return

        dice_msg = await context.bot.send_dice(chat_id=chat_id)
        dice_value = dice_msg.dice.value
        await asyncio.sleep(3)

        if user_id == duel["p1_id"]:
            duel["p1_score"] += dice_value
            duel["waiting_for"] = duel["p2_id"]
            await update.message.reply_markdown(
                f"🎲 {duel['p1_name']} تاس انداخت و عدد **{dice_value}** اومد!\n"
                f"📣 حالا نوبت {duel['p2_name']} است. بفرست: `/dice`"
            )
        else:
            duel["p2_score"] += dice_value
            current_round = duel["current_round"]
            total_rounds = duel["total_rounds"]

            await update.message.reply_markdown(
                f"🎲 {duel['p2_name']} تاس انداخت و عدد **{dice_value}** اومد!\n"
                f"📊 **وضعیت پایان راند {current_round}:**\n"
                f"🧔 {duel['p1_name']}: {duel['p1_score']} | 🧔 {duel['p2_name']}: {duel['p2_score']}"
            )

            if current_round >= total_rounds:
                p1_final = duel["p1_score"]
                p2_final = duel["p2_score"]
                
                if p1_final > p2_final:
                    winner_name, winner_id, loser_id = duel["p1_name"], duel["p1_id"], duel["p2_id"]
                    w_score, l_score = 40, -20
                    result_text = f"👑 **{winner_name} با مجموع امتیاز {p1_final} حریف خود را پودر کرد و پیروز میدان شد!** 👑"
                elif p2_final > p1_final:
                    winner_name, winner_id, loser_id = duel["p2_name"], duel["p2_id"], duel["p1_id"]
                    w_score, l_score = 40, -20
                    result_text = f"👑 **{winner_name} با مجموع امتیاز {p2_final} حریف خود را پودر کرد و پیروز میدان شد!** 👑"
                else:
                    winner_id, loser_id = None, None
                    result_text = f"🤝 **هر دو جنگجو در امتیاز {p1_final} مساوی شدند! نبرد بدون خون‌ریزی تمام شد.**"

                if winner_id:
                    update_stats(winner_id, w_score, True)
                    update_stats(loser_id, l_score, False)
                    await context.bot.send_message(chat_id=chat_id, text="💥")

                await context.bot.send_message(
                    chat_id=chat_id, 
                    text=f"🏁 **پایان نبرد نهایی دوئل** 🏁\n\n{result_text}\n\n🏆 جدول مدال‌ها به روز رسانی شد.",
                    parse_mode="Markdown"
                )
                del ACTIVE_DUELS[chat_id]
            else:
                duel["current_round"] += 1
                duel["waiting_for"] = duel["p1_id"]
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚔️ **راند {duel['current_round']} آغاز شد!**\n📣 {duel['p1_name']} تاس اول را پرتاب کن: `/dice`"
                )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="❌ سیستم با باگ مواجه شد:", exc_info=context.error)

# ==========================================
# ۸. اجرای کلاینت ربات
# ==========================================
def main():
    if BOT_TOKEN == "YOUR_DEFAULT_TOKEN_IF_NOT_SET":
        print("❌ خطا: توکن ربات تنظیم نشده است. لطفاً متغیر محیطی BOT_TOKEN را تنظیم کنید.")
        return

    application = Application.builder().token(BOT_TOKEN).job_queue(None).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("dice", dice_command))
    application.add_handler(CommandHandler("duel", duel_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("top", top_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("shop", shop_command))

    application.add_handler(CallbackQueryHandler(admin_buttons, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(shop_callback, pattern="^buy_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, monitor_messages_and_inputs))

    application.add_error_handler(error_handler)

    print("🚀 ربات کلوب نبرد تاس همراه با هماهنگی کامل هارد ریل‌وی آنلاین شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
