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
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_DEFAULT_TOKEN_IF_NOT_SET")
INITIAL_ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))

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
    top_users = cursor.execute('SELECT telegram_id, username, rank, title, score FROM users ORDER BY score DESC LIMIT 10').fetchall()
    conn.close(); return top_users

# ==========================================
# ۲. سیستم کنترل‌ها و وضعیت‌های فعال بازی
# ==========================================
USER_COOLDOWNS = {}
COOLDOWN_TIME = 1.5
ADMIN_STATES = {}
PV_DUEL_STATES = {}  # برای ذخیره وضعیت انتظار شماره حریف در پیوی

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
        "⚔️ `/duel [راند]` — **دوئل رگباری در گروه** (روی پیام حریف ریپلای کن)\n"
        "🏪 `/shop` — بازارچه لقب‌های حماسی\n"
        "👤 `/profile` — نمایش رنک و کارنامه جنگی\n"
        "🏆 `/top` — جدول ۱۰ مبارز برتر و دوئل پیوی\n"
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
    
    score_gained, is_win = 0, False
    if dice_value == 6: score_gained, is_win = 50, True
    elif dice_value == 5: score_gained, is_win = 30, True
    elif dice_value == 4: score_gained, is_win = 20, True
    elif dice_value == 3: score_gained, is_win = 10, True
    elif dice_value == 2: score_gained, is_win = -5, False
    elif dice_value == 1: score_gained, is_win = -15, False
    
    result = update_stats(user_id, score_gained, is_win)
    response = f"👤 **مبارز:** {user_data['username']}{title_tag}\n🎲 **تاس:** 〖 **{dice_value}** 〗\n🏆 **امتیاز:** {score_gained:+} XP"
    if result["rank_changed"]: response += f"\n🎖️ **ارتقا رتبه به: {result['new_rank']}**"
    await update.message.reply_markdown(response)

# ==========================================
# ۳. سیستم دوئل گروهی (ریپلای خودکار)
# ==========================================
async def duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ برای شروع دوئل گروهی، باید این دستور را روی پیام حریف ریپلای کنید!")
        return

    p1 = update.effective_user
    p2 = update.message.reply_to_message.from_user
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
            if rounds < 1 or rounds > 7: rounds = 3
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
        f"⚔️ **درخواست دوئل گروهی!**\n\n👤 **شروع‌کننده:** {p1_name}\n🎯 **حریف:** {p2_name}\n🏁 **راند:** {rounds}\n\nآیا قبول می‌کنی؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==========================================
# ۴. سیستم تاپ پلیرها + دوئل اختصاصی پیوی (PvP)
# ==========================================
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
    
    # دکمه شیشه‌ای برای دوئل در پیوی
    keyboard = [[InlineKeyboardButton("⚔️ دوئل با برترین‌ها (مخصوص پیوی)", callback_data="pv_duel_start")]]
    await update.message.reply_markdown(leaderboard_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    # --- شروع فرآیند دوئل پیوی ---
    if query.data == "pv_duel_start":
        if query.message.chat.type != "private":
            await query.answer("❌ این قابلیت فقط در پیوی (کامپکت خصوصی با ربات) کار می‌کند!", show_alert=True)
            return
        await query.answer()
        PV_DUEL_STATES[user_id] = "WAITING_FOR_TARGET_NUMBER"
        await query.message.reply_text("🎯 **لطفاً شماره بازیکن مورد نظر خود را از لیست بالا وارد کنید (مثلاً عدد 1 برای نفر اول):**")
        return

    # --- پذیرش یا رد دوئل در پیوی توسط حریف ---
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
            await query.answer()
            await query.edit_message_text("⚔️ **دوئل آغاز شد! در حال پرتاب تاس‌ها...**")
            try: await context.bot.send_message(chat_id=p1_id, text="⚔️ **حریف درخواست را قبول کرد! نبرد آغاز شد...**")
            except: pass

            # گلچین نام‌ها
            conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
            p1_name = cursor.execute('SELECT username FROM users WHERE telegram_id = ?', (p1_id,)).fetchone()['username']
            p2_name = cursor.execute('SELECT username FROM users WHERE telegram_id = ?', (p2_id,)).fetchone()['username']
            conn.close()

            p1_total, p2_total = 0, 0

            # راندها فیکس روی ۳ راند برای پیوی
            # --- راند ۱ تا ۳ بازیکن اول ---
            try: await context.bot.send_message(chat_id=p1_id, text=f"🎲 پرتاب ۳ تاس شما ({p1_name}):")
            except: pass
            try: await context.bot.send_message(chat_id=p2_id, text=f"🎲 پرتاب ۳ تاس حریف ({p1_name}) در حال ارسال برای شما:")
            except: pass

            for _ in range(3):
                # پرتاب برای پیوی نفر اول
                try:
                    d_msg = await context.bot.send_dice(chat_id=p1_id)
                    p1_total += d_msg.dice.value
                    # ارسال همان مقدار تاس برای پیوی نفر دوم جهت تماشا
                    await context.bot.send_message(chat_id=p2_id, text=f"تاس {p1_name}: 〖 **{d_msg.dice.value}** 〗")
                except: pass
                await asyncio.sleep(0.5)

            await asyncio.sleep(3.5)

            # --- راند ۱ تا ۳ بازیکن دوم ---
            try: await context.bot.send_message(chat_id=p2_id, text=f"🎲 حالا پرتاب ۳ تاس شما ({p2_name}):")
            except: pass
            try: await context.bot.send_message(chat_id=p1_id, text=f"🎲 پرتاب ۳ تاس حریف ({p2_name}) در حال ارسال برای شما:")
            except: pass

            for _ in range(3):
                try:
                    d_msg = await context.bot.send_dice(chat_id=p2_id)
                    p2_total += d_msg.dice.value
                    # ارسال برای پیوی نفر اول جهت تماشا
                    await context.bot.send_message(chat_id=p1_id, text=f"تاس {p2_name}: 〖 **{d_msg.dice.value}** 〗")
                except: pass
                await asyncio.sleep(0.5)

            await asyncio.sleep(3.5)

            # محاسبه و اعلام کل نتیجه در پیوی هردو
            if p1_total > p2_total:
                res_p1 = f"👑 **شما پیروز شدید! ({p1_total} vs {p2_total})** 🎉 (+40 XP)"
                res_p2 = f"💀 **شما باختید! ({p2_total} vs {p1_total})** (-20 XP)"
                update_stats(p1_id, 40, True)
                update_stats(p2_id, -20, False)
            elif p2_total > p1_total:
                res_p1 = f"💀 **شما باختید! ({p1_total} vs {p2_total})** (-20 XP)"
                res_p2 = f"👑 **شما پیروز شدید! ({p2_total} vs {p1_total})** 🎉 (+40 XP)"
                update_stats(p2_id, 40, True)
                update_stats(p1_id, -20, False)
            else:
                res_p1 = res_p2 = f"🤝 **نتیجه مساوی شد! ({p1_total} == {p2_total})**"

            try: await context.bot.send_message(chat_id=p1_id, text=f"🏁 **نتیجه نهایی:**\n\n{res_p1}")
            except: pass
            try: await context.bot.send_message(chat_id=p2_id, text=f"🏁 **نتیجه نهایی:**\n\n{res_p2}")
            except: pass
            return

    # --- هندل کالبک دوئل‌های گروهی سنتی ---
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
                txt = f"👑 **{p1_name} پیروز شد!**"
                update_stats(p1_id, 40, True); update_stats(p2_id, -20, False)
            elif p2_total > p1_total:
                txt = f"👑 **{p2_name} پیروز شد!**"
                update_stats(p2_id, 40, True); update_stats(p1_id, -20, False)
            else: txt = "🤝 **مساوی!**"
            await context.bot.send_message(chat_id=chat_id, text=txt)

    # مدیریت دکمه‌های ادمین و خرید لقب
    if data[0] == "admin": await admin_buttons(update, context)
    if data[0] == "buy": await shop_callback(update, context)

# ==========================================
# ۵. مانیتورینگ پیام‌ها، چت‌ها و ورودی‌های متنی عددی
# ==========================================
async def monitor_messages_and_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    p_name = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    get_or_create_user(user_id, p_name)

    # --- هندل کردن دریافت شماره بازیکن برای دوئل پیوی ---
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
            await update.message.reply_text("❌ شوخی قشنگی بود ولی نمی‌توانی به خودت درخواست دوئل بدهی!")
            return

        # ارسال پیامک درخواست به پیوی حریف
        keyboard = [[
            InlineKeyboardButton("⚔️ قبول نبرد", callback_data=f"pvduel_yes_{user_id}_{target_id}"),
            InlineKeyboardButton("🏳️ رد درخواست", callback_data=f"pvduel_no_{user_id}_{target_id}")
        ]]

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"⚔️ **یک درخواست دوئل پیوی دریافت کردید!**\n\n👤 **فرستنده:** @{p_name}\n🎖️ آیا چالش این مبارز را برای یک بازی ۳ رانده تمام‌عیار می‌پذیرید؟",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            await update.message.reply_markdown(f"🚀 **درخواست دوئل پیوی شما با موفقیت برای @{target_name} ارسال شد.**\nمنتظر تایید او بمانید...")
        except Exception:
            await update.message.reply_text("❌ متاسفانه نتوانستم به پیوی حریف پیام بفرستم! (شاید ربات را بلاک کرده یا استارت نزده است)")
        return

    # کنترل پنل ادمین
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

# ==========================================
# ۶. بخش‌های جانبی سیستم فروشگاه و ادمین
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
    query = update.callback_query; user_id = query.from_user.id; data = query.data
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

    application.add_handler(CallbackQueryHandler(handle_callbacks, pattern="^(pv_duel_start|pvduel_|gduel_|admin_|buy_)"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, monitor_messages_and_inputs))

    print("🚀 ربات با قابلیت نبرد پیوی متقابل (PvP) آنلاین شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
