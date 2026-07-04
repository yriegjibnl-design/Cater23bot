import os
import random
import sqlite3
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

DB_FILE = "/app/data/games.db"

# ==========================================
# ۱. راه‌اندازی دیتابیس
# ==========================================
def init_db():
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
            telegram_id INTEGER PRIMARY KEY, added_at TEXT
        )
    ''')
    cursor.execute('INSERT OR IGNORE INTO admins (telegram_id, added_at) VALUES (?, ?)', 
                   (INITIAL_ADMIN_ID, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
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
        name = clean_username if clean_username else f"User_{telegram_id}"
        cursor.execute('INSERT INTO users (telegram_id, username, created_at, last_seen) VALUES (?, ?, ?, ?)', 
                       (telegram_id, name, now_str, now_str))
        conn.commit()
        user = cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)).fetchone()
    else:
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
    top_users = cursor.execute('SELECT username, rank, title, score FROM users ORDER BY score DESC LIMIT 10').fetchall()
    conn.close(); return top_users

# ==========================================
# ۲. سیستم دوئل خودکار و تاییدیه ریپلای
# ==========================================
USER_COOLDOWNS = {}
COOLDOWN_TIME = 1.5
ADMIN_STATES = {}

async def check_cooldown(update: Update) -> bool:
    if not update.message: return False
    user_id = update.effective_user.id
    now = datetime.now().timestamp()
    if user_id in USER_COOLDOWNS and now < USER_COOLDOWNS[user_id]:
        await update.message.reply_text('⚡ **آرام‌تر! چند لحظه صبر کن.**')
        return False
    USER_COOLDOWNS[user_id] = now + COOLDOWN_TIME
    return True

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    user = update.effective_user
    get_or_create_user(user.id, user.username if user.username else user.first_name)
    await update.message.reply_markdown(f"🔥 **سلام {user.first_name}! به کلوب رسمی نبرد تاس خوش آمدی!**\n\nبرای دیدن فرمان‌ها دستور `/help` رو بفرست! ⚔️")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    help_text = (
        "⚔️ 🔴 **لیست فرمان‌های نبرد کلوب تاس** 🔴 ⚔️\n\n"
        "🎲 `/dice` — پرتاب تاس شانسی انفرادی\n"
        "⚔️ `/duel [تعداد راند]` — **دوئل رگباری و خودکار!** (روی پیام حریف ریپلای کن. مثال: `/duel 3`)\n"
        "🏪 `/shop` — بازارچه لقب‌های حماسی\n"
        "👤 `/profile` — نمایش رنک و کارنامه جنگی\n"
        "🏆 `/top` — جدول ۱۰ مبارز برتر\n"
    )
    if is_user_admin(update.effective_user.id): help_text += "⚙️ `/admin` — کنترل پنل مدیریت"
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
    if dice_value == 6: score_gained, is_win, status_text = 50, True, "🔥 **شــــــــــش ملوووووووک!**"
    elif dice_value == 5: score_gained, is_win, status_text = 30, True, "😎 عالی!"
    elif dice_value == 4: score_gained, is_win, status_text = 20, True, "👍 خوب."
    elif dice_value == 3: score_gained, is_win, status_text = 10, True, "😐 معمولی."
    elif dice_value == 2: score_gained, is_win, status_text = -5, False, "🤏 بدشانسی."
    elif dice_value == 1: score_gained, is_win, status_text = -15, False, "💀 تاس کفتار گریبان‌گیرت شد!"
    
    result = update_stats(user_id, score_gained, is_win)
    response = f"👤 **مبارز:** {user_data['username']}{title_tag}\n🎲 **تاس:** 〖 **{dice_value}** 〗\n🏆 **امتیاز:** {score_gained:+} XP"
    if result["rank_changed"]: response += f"\n🎖️ **ارتقا رتبه به: {result['new_rank']}**"
    await update.message.reply_markdown(response)

# --- سیستم دوئل ارتقا یافته کاملاً خودکار ---
async def duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ برای شروع دوئل، باید این دستور را روی پیام حریف خود ریپلای کنید!")
        return

    p1 = update.effective_user
    p2 = update.message.reply_to_message.from_user
    p2_msg_id = update.message.reply_to_message.message_id
    p1_msg_id = update.message.message_id

    if p1.id == p2.id:
        await update.message.reply_text("❌ دیوانه شدی؟ نمی‌توانی با خودت دوئل کنی!")
        return
    if p2.is_bot: return

    rounds = 3
    if context.args:
        try:
            rounds = int(context.args[0])
            if rounds < 1 or rounds > 7: rounds = 3
        except ValueError: pass

    p1_name = p1.username if p1.username else p1.first_name
    p2_name = p2.username if p2.username else p2.first_name

    get_or_create_user(p1.id, p1_name)
    get_or_create_user(p2.id, p2_name)

    # ساخت دکمه شیشه‌ای جهت دریافت تایید از حریف
    keyboard = [
        [
            InlineKeyboardButton("⚔️ قبول می‌کتم (آره)", callback_data=f"duel_yes_{p1.id}_{p2.id}_{rounds}_{p1_msg_id}_{p2_msg_id}"),
            InlineKeyboardButton("🏳️ ترسو هستم (نه)", callback_data=f"duel_no_{p2.id}")
        ]
    ]
    
    await update.message.reply_markdown(
        f"⚔️ **درخواست دوئل مرگبار!** ⚔️\n\n"
        f"👤 **شروع‌کننده:** {p1_name}\n"
        f"🎯 **حریف دعوت‌شده:** {p2_name}\n"
        f"🏁 **تعداد راند درخواستی:** {rounds} راند\n\n"
        f"🔥 {p2_name} عزیز، آیا درخواست دوئل رو قبول می‌کنی؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def duel_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    chat_id = query.message.chat_id
    
    if data[1] == "no":
        target_p2_id = int(data[2])
        if query.from_user.id != target_p2_id:
            await query.answer("❌ این دکمه مال تو نیست حبیبی!", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text(f"🏳️ **دوئل لغو شد!** {query.from_user.first_name} ترسید و عقب‌نشینی کرد.")
        return

    if data[1] == "yes":
        p1_id = int(data[2])
        p2_id = int(data[3])
        rounds = int(data[4])
        p1_msg_id = int(data[5])
        p2_msg_id = int(data[6])

        if query.from_user.id != p2_id:
            await query.answer("❌ فقط حریف دعوت شده می‌تواند نبرد را قبول کند!", show_alert=True)
            return
            
        await query.answer()
        await query.edit_message_text("⚔️ **نبرد تایید شد! تاس‌ها در حال چرخش و پرتاب رگباری...**")

        # گرفتن نام‌ها از دیتابیس
        conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        p1_db = cursor.execute('SELECT username FROM users WHERE telegram_id = ?', (p1_id,)).fetchone()
        p2_db = cursor.execute('SELECT username FROM users WHERE telegram_id = ?', (p2_id,)).fetchone()
        conn.close()

        p1_name = p1_db['username'] if p1_db else "Player 1"
        p2_name = p2_db['username'] if p2_db else "Player 2"

        p1_total = 0
        p2_total = 0

        # --- پرتاب تاس رگباری برای بازیکن اول (ریپلای روی پیام خودش) ---
        await context.bot.send_message(chat_id=chat_id, text=f"🎲 **پرتاب رگباری تاس‌ها برای {p1_name}:**", reply_to_message_id=p1_msg_id)
        for r in range(rounds):
            d_msg = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p1_msg_id)
            p1_total += d_msg.dice.value
            await asyncio.sleep(0.5) # تاخیر کم برای قاطی نشدن انیمیشن تاس‌ها

        await asyncio.sleep(3.5) # زمان برای پایان انیمیشن آخرین تاس بازیکن اول
        await context.bot.send_message(chat_id=chat_id, text=f"📊 مجموع امتیاز {p1_name} شد: **{p1_total}**", reply_to_message_id=p1_msg_id)

        # --- پرتاب تاس رگباری برای بازیکن دوم (ریپلای روی پیام خودش) ---
        await context.bot.send_message(chat_id=chat_id, text=f"🎲 **پرتاب رگباری تاس‌ها برای {p2_name}:**", reply_to_message_id=p2_msg_id)
        for r in range(rounds):
            d_msg = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p2_msg_id)
            p2_total += d_msg.dice.value
            await asyncio.sleep(0.5)

        await asyncio.sleep(3.5)
        await context.bot.send_message(chat_id=chat_id, text=f"📊 مجموع امتیاز {p2_name} شد: **{p2_total}**", reply_to_message_id=p2_msg_id)

        # --- محاسبه نتیجه نهایی کُل نبرد ---
        if p1_total > p2_total:
            winner_name, winner_id, loser_id = p1_name, p1_id, p2_id
            result_txt = f"👑 **پایان نبرد حماسی! {winner_name} با نتیجه {p1_total} بر {p2_total} پیروز بزرگ میدان شد!** 🎉"
            update_stats(winner_id, 40, True)
            update_stats(loser_id, -20, False)
        elif p2_total > p1_total:
            winner_name, winner_id, loser_id = p2_name, p2_id, p1_id
            result_txt = f"👑 **پایان نبرد حماسی! {winner_name} با نتیجه {p2_total} بر {p1_total} پیروز بزرگ میدان شد!** 🎉"
            update_stats(winner_id, 40, True)
            update_stats(loser_id, -20, False)
        else:
            result_txt = f"🤝 **عجب مسابقه‌ای! هر دو گلادیاتور در امتیاز نهایی {p1_total} برابر شدند! بازی مساوی پایان یافت.**"

        await context.bot.send_message(chat_id=chat_id, text=f"🏁 **نتیجه نهایی کلوب نبرد ({rounds} رانده):**\n\n{result_txt}\n\n🏆 دیتابیس امتیازات بروزرسانی شد.")

# ==========================================
# ۳. سایر بخش‌های ربات (پروفایل، شاپ، تاپ، ادمین)
# ==========================================
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
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
    await update.message.reply_markdown(profile_text)

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    top_players = get_top_players()
    if not top_players:
        await update.message.reply_text("📊 تالار افتخارات خالی است.")
        return
    leaderboard_text = "🏆 **تالار مشاهیر و ۱۰ گلادیاتور برتر کلوب** 🏆\n\n"
    for index, player in enumerate(top_players):
        medals = "👑" if index == 0 else "⚡" if index == 1 else "🛡️" if index == 2 else "🎖️"
        title_tag = f" ({player['title']})" if player['title'] != 'بدون لقب' else ""
        leaderboard_text += f"{medals} {index + 1}. **{player['username']}**{title_tag}\n  Rank: {player['rank']} | ⭐ {player['score']} XP\n\n"
    await update.message.reply_markdown(leaderboard_text)

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    if user['rank'] != "👑 Master":
        await update.message.reply_markdown("🔒 **دسترسی محدود!**\nابتدا باید به رنک نهایی یعنی **👑 Master** برسید!")
        return
    keyboard = []
    for key, item in SHOP_TITLES.items():
        keyboard.append([InlineKeyboardButton(f"{item['name']} 💰 {item['cost']} امتیاز", callback_data=f"buy_{key}")])
    await update.message.reply_text(f"🏪 **به بازارچه خوش آمدی!**\n💰 موجودی: {user['score']} XP", reply_markup=InlineKeyboardMarkup(keyboard))

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = query.from_user.id; data = query.data
    if not data.startswith("buy_"): return
    await query.answer()
    title_key = data.split("_")[1]
    if title_key not in SHOP_TITLES: return
    item = SHOP_TITLES[title_key]
    user = get_or_create_user(user_id, query.from_user.username if query.from_user.username else query.from_user.first_name)
    if user['rank'] != "👑 Master" or user['score'] < item['cost']: return
    
    new_score = user['score'] - item['cost']
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute('UPDATE users SET score = ?, title = ? WHERE telegram_id = ?', (new_score, item['name'], user_id))
    conn.commit(); conn.close()
    await query.edit_message_text(f"🎉 **لقب حماسی « {item['name']} » فعال شد!**")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_user_admin(update.effective_user.id): return
    keyboard = [
        [InlineKeyboardButton("📊 لیست کاربران", callback_data="admin_users")],
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🚀 ارتقا به Master", callback_data="admin_set_master")],
        [InlineKeyboardButton("🧹 صفر کردن امتیاز", callback_data="admin_reset_score")],
        [InlineKeyboardButton("❌ بستن پنل", callback_data="admin_close")]
    ]
    await update.message.reply_text("🛠 **اتاق فرمان مدیریت:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = query.from_user.id
    if not is_user_admin(user_id): return
    await query.answer(); data = query.data

    if data == "admin_users":
        conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        users = cursor.execute('SELECT username, score, rank FROM users ORDER BY score DESC LIMIT 15').fetchall(); conn.close()
        txt = "📊 **آمار کاربران:**\n\n"
        for idx, u in enumerate(users): txt += f"{idx+1}. 👤 @{u['username']} | ⭐ {u['score']} XP | {u['rank']}\n"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))
    elif data == "admin_broadcast":
        ADMIN_STATES[user_id] = "WAITING_FOR_BROADCAST"
        await query.edit_message_text("📢 متن پیام همگانی خود را ارسال کنید:")
    elif data == "admin_set_master":
        ADMIN_STATES[user_id] = "WAITING_FOR_USERNAME_MASTER"
        await query.edit_message_text("🚀 نام کاربری فرد مورد نظر را بدون @ بفرستید:")
    elif data == "admin_reset_score":
        ADMIN_STATES[user_id] = "WAITING_FOR_USERNAME_RESET"
        await query.edit_message_text("🧹 نام کاربری فرد مورد نظر را بدون @ بفرستید:")
    elif data == "admin_close":
        await query.edit_message_text("🔒 پنل مدیریت بسته شد.")

async def monitor_messages_and_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)

    if user_id in ADMIN_STATES:
        state = ADMIN_STATES[user_id]
        if state == "WAITING_FOR_BROADCAST":
            del ADMIN_STATES[user_id]
            conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
            rows = cursor.execute('SELECT telegram_id FROM users').fetchall(); conn.close()
            for row in rows:
                try: await context.bot.send_message(chat_id=row[0], text=f"📢 **اطلاعیه مدیریت:**\n\n{text}", parse_mode="Markdown")
                except: continue
            await update.message.reply_text("✅ فرستاده شد.")
        elif state == "WAITING_FOR_USERNAME_MASTER":
            del ADMIN_STATES[user_id]; target = text.replace("@", "")
            conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
            cursor.execute("UPDATE users SET score = 6000, rank = '👑 Master' WHERE username = ?", (target,))
            changes = conn.total_changes; conn.commit(); conn.close()
            await update.message.reply_text("🚀 ارتقا یافت." if changes > 0 else "❌ پیدا نشد.")
        elif state == "WAITING_FOR_USERNAME_RESET":
            del ADMIN_STATES[user_id]; target = text.replace("@", "")
            conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
            cursor.execute("UPDATE users SET score = 0, rank = '🥉 Bronze I', title = 'بدون لقب' WHERE username = ?", (target,))
            changes = conn.total_changes; conn.commit(); conn.close()
            await update.message.reply_text("🧹 صفر شد." if changes > 0 else "❌ پیدا نشد.")

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

    application.add_handler(CallbackQueryHandler(duel_callback_handler, pattern="^duel_"))
    application.add_handler(CallbackQueryHandler(admin_buttons, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(shop_callback, pattern="^buy_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, monitor_messages_and_inputs))

    print("🚀 ربات با مکانیزم جدید دوئل رگباری آنلاین شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
