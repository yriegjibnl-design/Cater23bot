import os
import random
import sqlite3
import logging
import asyncio
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

# وارد کردن توابع اختصاصی مدیریت دیتابیس از فایل جانبی
from database import init_db, is_user_admin, get_or_create_user, update_stats, get_top_players, calculate_rank, DB_FILE

# ==========================================
# تنظیمات اصلی ربات از طریق محیط سرور
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8894117383:AAFGeDmC1lnY_LoFaah7zTAX7NjriIb2-Tc")
INITIAL_ADMIN_ID = int(os.getenv("ADMIN_ID", "7430881772"))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# راه‌اندازی اولیه فایل دیتابیس جداگانه
init_db(INITIAL_ADMIN_ID)

# 🎰 امتیازدهی جدید تاس‌ها
DICE_SCORES = {
    1: -5,
    2: 5,
    3: 10,
    4: 15,
    5: 25,
    6: 40
}

CAT_NAMES = {
    "normal": "لقب عادی",
    "epic": "لقب افسانه‌ای",
    "legendary": "لقب لجندری"
}

DICE_MOTIVATIONS = {
    6: ["🔥 **شــــــــــش ملوووووووک! میدان نبرد به آتش کشیده شد!**", "😎 شش چرخ روزگار به کامت چرخید! فوق‌العاده بود!"],
    5: ["⚡ **بسیار عالی! شانس با تو همراهه جنگجو!**", "💪 یک پرتاب قدرتمند و بی‌نقص!"],
    4: ["👍 **خوب و مطمئن! قدم به قدم به پیروزی نزدیک‌تر میشی.**", "🛡️ پرتابی محکم برای حفظ موقعیت!"],
    3: ["😐 **معمولی و متوسط... می‌تونست خیلی بهتر باشه!**", "💫 شانس وسط زمین ایستاده، پرتاب بعدی رو محکم‌تر بزن!"],
    2: ["🤏 **امتیاز کمی بود! بوی بدشانسی میاد...**", "🌪️ تاس موافقی نبود، ولی غمت نباشه جنگجو!"],
    1: ["💀 **تاس کفتار گریبان‌گیرت شد! سقوط آزاد امتیاز!**", "❌ تاس کفتار تمام نقشه‌هات رو نقش بر آب کرد!"]
}

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
    
    # ⚔️ متن خوش‌آمدگویی حماسی، گنگ و به شدت گنگستر جایگزین متن قبلی شد!
    welcome_text = (
        f"⚔️ **به قلمرو خونین و بی‌رحم «نبرد تاس» خوش آمدی، {user.first_name}!** ⚔️\n\n"
        f"اینجا جایی نیست که با خواهش و تمنا امتیاز جمع کنی! اینجا کلوپ گلادیاتورهاست؛ "
        f"جایی که شانس فقط به شجاع‌ها رو می‌کنه و یک پرتاب اشتباه، می‌تونه تو رو به قعر جدول بفرسته! 💀\n\n"
        f"⚡ **تاس‌های عادلانه مستقر شدن، بازارچه تگ‌های جنگی آمادست و حریف‌ها دندون تیز کردن!**\n"
        f"دستت رو بذار روی دکمه، تاس رو پرتاب کن و ثابت کن شاهِ این میدونی یا فقط یه تماشاچی! 🔥"
    )
    
    await update.message.reply_markdown(welcome_text, reply_markup=get_main_menu_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_cooldown(update): return
    help_text = (
        "⚔️ 🔴 **لیست فرمان‌های نبرد کلوب تاس (آپدیت بزرگ)** 🔴 ⚔️\n\n"
        "🎲 `🎲 پرتاب تاس` — پرتاب تاس انفرادی (دارای شانس حمله بحرانی متوالی)\n"
        "⚔️ `/duel [راند]` — **دوئل رگباری در گروه** (حداکثر تا ۶ راند)\n"
        "🏪 `🏪 بازارچه لقب` — خرید دسته‌بندی‌شده انواع تگ و لقب‌ها\n"
        "👤 `👤 پروفایل من` — نمایش کارنامه جنگی با احتساب مساوی‌ها\n"
        "🏆 `🏆 تالار افتخارات` — جدول مشاهیر و ۱۰ گلادیاتور برتر کلوب\n"
        "🔑 `/redeem [کد]` — فعال‌سازی کدهای هدیه و لقب‌های موقت ادمین\n"
    )
    if is_user_admin(update.effective_user.id): help_text += "\n⚙️ `/admin` — کنترل پنل فوق پیشرفته اتاق فرماندهی"
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

def log_score_source(telegram_id, game_type):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO score_logs (telegram_id, game_type, count) VALUES (?, ?, 1)
        ON CONFLICT(telegram_id, game_type) DO UPDATE SET count = count + 1
    ''', (telegram_id, game_type))
    conn.commit(); conn.close()

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
        f"🏆 **تغییرات امتیاز:** {sign}{score_gained} XP"
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
                res_p1 = f"🏆 **حماسه آفریدی جنگجو!**\n\nشما با اقتدار و مجموع تاس `{p1_total}` در مقابل مجموع تاس `{p2_total}` حریف رو خاک کردید و فاتح دوعل شدید! 🏅\n(+40 XP)"
                res_p2 = f"💀 **شکست سنگین در میدان مبارزه!**\n\nمجموع تاس شما `{p2_total}` حریف رو پیروز میدان کرد (`{p1_total}`). امتیاز از دست دادید.\n(+5 XP)"
                update_stats(p1_id, 40, 'win')
                update_stats(p2_id, 5, 'loss')
                log_score_source(p1_id, "duel")
                log_score_source(p2_id, "duel")
            elif p2_total > p1_total:
                res_p1 = f"💀 **شکست سنگین در میدان مبارزه!**\n\nمجموع تاس شما `{p1_total}` حریف رو پیروز میدان کرد (`{p2_total}`). امتیاز از دست دادید.\n(+5 XP)"
                res_p2 = f"🏆 **حماسه آفریدی جنگجو!**\n\nشما با اقتدار و مجموع تاس `{p2_total}` در مقابل مجموع تاس `{p1_total}` حریف رو خاک کردید و فاتح دوعل شدید! 🏅\n(+40 XP)"
                update_stats(p2_id, 40, 'win')
                update_stats(p1_id, 5, 'loss')
                log_score_source(p1_id, "duel")
                log_score_source(p2_id, "duel")
            else:
                res_p1 = res_p2 = f"🤝 **نبرد برابر و بی‌پایان!**\n\nهر دو جنگجو مجموعاً امتیاز `{p1_total}` آوردند! این مبارزه برنده‌ای نداشت و نتیجه مساوی ثبت شد."
                update_stats(p1_id, 0, 'draw')
                update_stats(p2_id, 0, 'draw')
                log_score_source(p1_id, "duel")
                log_score_source(p2_id, "duel")

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
                txt = f"🏆 **حماسه آفریدی جنگجو!**\n\n👤 **{p1_name}** با مجموع تاس `{p1_total}` حریف خود یعنی **{p2_name}** را در هم کوبید و پیروز نبرد شد! 🎉 (+40 XP)"
                update_stats(p1_id, 40, 'win')
                update_stats(p2_id, 5, 'loss')
                log_score_source(p1_id, "duel")
                log_score_source(p2_id, "duel")
            elif p2_total > p1_total:
                txt = f"🏆 **حماسه آفریدی جنگجو!**\n\n👤 **{p2_name}** با مجموع تاس `{p2_total}` حریف خود یعنی **{p1_name}** را در هم کوبید و پیروز نبرد شد! 🎉 (+40 XP)"
                update_stats(p2_id, 40, 'win')
                update_stats(p1_id, 5, 'loss')
                log_score_source(p1_id, "duel")
                log_score_source(p2_id, "duel")
            else:
                txt = f"🤝 **نبرد بی‌پایان و مساوی!**\n\nهر دو گلادیاتور به مجموع برابر `{p1_total}` رسیدند و این جنگ با نتیجه مساوی خاتمه یافت!"
                update_stats(p1_id, 0, 'draw')
                update_stats(p2_id, 0, 'draw')
                log_score_source(p1_id, "duel")
                log_score_source(p2_id, "duel")
            
            finish_time = datetime.now().timestamp() + 15.0
            DUEL_COOLDOWNS[p1_id] = finish_time
            DUEL_COOLDOWNS[p2_id] = finish_time
            
            await context.bot.send_message(chat_id=chat_id, text=txt)

    if data[0] == "admin": await admin_buttons(update, context)
    if data[0] == "shop": await shop_callback(update, context)

# ==========================================
# ۵. مانیتورینگ متن‌ها و اتصال دکمه‌های منو
# ==========================================
async def monitor_messages_and_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if not is_user_admin(user_id):
        now = datetime.now().timestamp()
        if user_id in USER_LAST_MESSAGE_TIME and (now - USER_LAST_MESSAGE_TIME[user_id]) < 60:
            return
        USER_LAST_MESSAGE_TIME[user_id] = now
    
    if is_user_admin(user_id) and ("تالار مشاهیر" in text or "۱۰ گلادیاتور برتر" in text) and "XP" in text:
        lines = text.split("\n")
        current_username = None
        updated_count = 0
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        for line in lines:
            user_match = re.search(r'(?:\d+\.\s*|👑|⚡|🛡️|🎖️)\s*([A-Za-z0-9_]+)', line)
            if user_match:
                current_username = user_match.group(1).strip()
            
            score_match = re.search(r'(?:⭐\s*|\b)(\d+)\s*XP', line)
            if score_match and current_username:
                score_val = int(score_match.group(1))
                rank_val = calculate_rank(score_val)
                
                user_check = cursor.execute("SELECT 1 FROM users WHERE username = ?", (current_username,)).fetchone()
                if user_check:
                    cursor.execute("UPDATE users SET score = ?, rank = ? WHERE username = ?", (score_val, rank_val, current_username))
                else:
                    fake_id = -random.randint(1000000, 9999999)
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute("INSERT INTO users (telegram_id, username, score, rank, created_at, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
                                   (fake_id, current_username, score_val, rank_val, now_str, now_str))
                
                updated_count += 1
                current_username = None
                
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
            
        elif state == "WAITING_FOR_REDEEM_CODE":
            ADMIN_STATES[user_id] = f"REDEEM_TITLE_{text}"
            await update.message.reply_text("✨ نام تگ یا لقبی که مایلید با این ردیم‌کد اهدا شود را ارسال کنید:")
            
        elif state.startswith("REDEEM_TITLE_"):
            rc_code = state.replace("REDEEM_TITLE_", "")
            ADMIN_STATES[user_id] = f"REDEEM_USES_{rc_code}_{text}"
            await update.message.reply_text("👥 تعداد دفعات مجاز استفاده از این ردیم کد چقدر باشد؟ (عدد وارد کنید):")
            
        elif state.startswith("REDEEM_USES_"):
            parts = state.split("_")
            rc_code = parts[2]
            rc_title = parts[3]
            try:
                rc_uses = int(text)
            except ValueError:
                await update.message.reply_text("❌ خطا! لطفا تعداد مجاز را به صورت عدد وارد کنید.")
                return
            ADMIN_STATES[user_id] = f"REDEEM_HOURS_{rc_code}_{rc_title}_{rc_uses}"
            await update.message.reply_text("⏱️ مدت زمان ماندگاری این تگ روی پروفایل کاربر چقدر باشد؟ (به ساعت، مثلاً 48):")
            
        elif state.startswith("REDEEM_HOURS_"):
            parts = state.split("_")
            rc_code = parts[2]
            rc_title = parts[3]
            rc_uses = int(parts[4])
            del ADMIN_STATES[user_id]
            try:
                rc_hours = int(text)
            except ValueError:
                await update.message.reply_text("❌ خطا! مدت زمان باید عدد باشد.")
                return
                
            conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO redeem_codes (code, title_name, max_uses, duration_hours) VALUES (?, ?, ?, ?)',
                           (rc_code, rc_title, rc_uses, rc_hours))
            conn.commit(); conn.close()
            await update.message.reply_text(f"✅ **ردیم کد با موفقیت ساخته شد!**\n🔑 کد: `{rc_code}`\n🏷️ تگ هدیه: **{rc_title}**\n👥 ظرفیت: {rc_uses} بار\n⏱️ مدت اعتبار تگ: {rc_hours} ساعت پس از فعال‌سازی.")

        elif state == "WAITING_FOR_SHOP_TITLE":
            ADMIN_STATES[user_id] = f"SHOP_CAT_{text}"
            keyboard = [
                [InlineKeyboardButton("🥈 لقب عادی", callback_data=f"setcat_normal_{text}")],
                [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data=f"setcat_epic_{text}")],
                [InlineKeyboardButton("👑 لقب لجندری", callback_data=f"setcat_legendary_{text}")]
            ]
            await update.message.reply_text("📂 دسته‌بندی لقب جدید را مشخص کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
            
        elif state.startswith("SHOP_PRICE_"):
            parts = state.split("_")
            new_title = parts[2]
            cat_type = parts[3]
            del ADMIN_STATES[user_id]
            try:
                price = int(text)
            except ValueError:
                await update.message.reply_text("❌ قیمت باید عدد باشد.")
                return
            conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO shop (title_name, cost, category) VALUES (?, ?, ?)", (new_title, price, cat_type))
                conn.commit()
                await update.message.reply_text(f"✅ لقب « {new_title} » با موفقیت در دسته **{CAT_NAMES[cat_type]}** با قیمت {price} XP اضافه شد.")
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
        f"🟢 پیروزی: {user['wins']}  |  🤝 مساوی: {user['draws']}  |  🔴 شکست: {user['losses']}\n🔥 **نرخ برد:** {win_rate}%\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    if update.message:
        await update.message.reply_markdown(profile_text, reply_markup=get_main_menu_keyboard())
    return profile_text

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal")],
        [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
        [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")]
    ]
    
    if update.message:
        await update.message.reply_text(
            f"🏪 **به بازارچه لقب‌ها خوش آمدی!**\n💰 موجودی شما: {user['score']} XP\n\nدسته‌بندی مورد نظر خود را انتخاب کنید:", 
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = query.from_user.id; data = query.data
    await query.answer()
    
    if data.startswith("shopmain_cat_"):
        cat_type = data.replace("shopmain_cat_", "")
        conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        shop_items = cursor.execute("SELECT id, title_name, cost FROM shop WHERE category = ?", (cat_type,)).fetchall(); conn.close()
        
        if not shop_items:
            await query.edit_message_text(f"🔒 در حال حاضر لقبی در بخش **{CAT_NAMES[cat_type]}** موجود نیست.", 
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منوی شاپ", callback_data="shopmain_back")]]))
            return
            
        keyboard = []
        for item in shop_items:
            keyboard.append([InlineKeyboardButton(f"{item['title_name']} 💰 {item['cost']} XP", callback_data=f"shopbuy_id_{item['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shopmain_back")])
        
        await query.edit_message_text(f"🛍️ **لیست لقب‌های بخش: {CAT_NAMES[cat_type]}**\nبرای خرید روی تگ مورد نظر کلیک کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "shopmain_back":
        keyboard = [
            [InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal")],
            [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
            [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")]
        ]
        await query.edit_message_text("🏪 **بازارچه لقب‌ها**\n\nدسته‌بندی مورد نظر خود را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data.startswith("shopbuy_id_"):
        item_id = int(data.split("_")[2])
        conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        item = cursor.execute("SELECT * FROM shop WHERE id = ?", (item_id,)).fetchone()
        
        if not item:
            conn.close(); return
            
        user = get_or_create_user(user_id, query.from_user.username if query.from_user.username else query.from_user.first_name)
        if user['score'] < item['cost']:
            await context.bot.send_message(chat_id=query.message.chat_id, text="❌ امتیاز کافی برای خرید این لقب را نداری مشتی! بیشتر بازی کن.")
            conn.close(); return
        
        new_score = user['score'] - item['cost']
        cursor.execute('UPDATE users SET score = ?, title = ? WHERE telegram_id = ?', (new_score, item['title_name'], user_id))
        conn.commit(); conn.close()
        await query.edit_message_text(f"🎉 **لقب حماسی اختصاصی « {item['title_name']} » با موفقیت خریداری و بر روی پروفایل شما فعال شد!**")

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ فرمت استفاده اشتباه است. لطفا کد را جلوش وارد کنید. مثال: `/redeem ARIA88`")
        return
        
    code = context.args[0].strip()
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
    
    cdata = cursor.execute('SELECT * FROM redeem_codes WHERE code = ?', (code,)).fetchone()
    if not cdata:
        await update.message.reply_text("❌ چنین ردیم کدی وجود ندارد یا منقضی شده است."); conn.close(); return
        
    if cdata['current_uses'] >= cdata['max_uses']:
        await update.message.reply_text("❌ ظرفیت استفاده از این ردیم کد به اتمام رسیده است."); conn.close(); return
        
    hist = cursor.execute('SELECT 1 FROM redeem_history WHERE telegram_id = ? AND code = ?', (user_id, code)).fetchone()
    if hist:
        await update.message.reply_text("❌ شما قبلاً یکبار از این ردیم کد استفاده کرده‌اید."); conn.close(); return
        
    expire_time = (datetime.now() + timedelta(hours=cdata['duration_hours'])).strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute('INSERT INTO redeem_history (telegram_id, code, used_at) VALUES (?, ?, ?)', (user_id, code, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    cursor.execute('UPDATE redeem_codes SET current_uses = current_uses + 1 WHERE code = ?', (code,))
    cursor.execute('UPDATE users SET title = ?, title_expire = ? WHERE telegram_id = ?', (cdata['title_name'], expire_time, user_id))
    conn.commit(); conn.close()
    
    await update.message.reply_text(f"🎉 **کد هدیه با موفقیت فعال شد!**\nلقب موقت **{cdata['title_name']}** به مدت {cdata['duration_hours']} ساعت به شما تعلق گرفت.")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_user_admin(update.effective_user.id): return
    keyboard = [
        [InlineKeyboardButton("📊 لیست کاربران", callback_data="admin_users"), InlineKeyboardButton("🏆 تالار مشاهیر", callback_data="admin_top")],
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"), InlineKeyboardButton("🔄 باز‌یابی پیام رنک", callback_data="admin_restore_msg")],
        [InlineKeyboardButton("🚀 ارتقا امتیاز دلخواه", callback_data="admin_set_score"), InlineKeyboardButton("🧹 صفر کردن امتیاز", callback_data="admin_reset_score")],
        [InlineKeyboardButton("➕ افزودن تگ جدید به شاپ", callback_data="admin_add_shop"), InlineKeyboardButton("🔑 ساخت ردیم کد", callback_data="admin_make_redeem")],
        [InlineKeyboardButton("📊 رهگیری آمار امتیازگیری", callback_data="admin_check_logs")],
        [InlineKeyboardButton("❌ بستن پنل", callback_data="admin_close")]
    ]
    await update.message.reply_text("🛠 **اتاق فرمان مدیریت پیشرفته و پویای ربات:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = query.from_user.id; data = query.data
    
    if data.startswith("setcat_"):
        parts = data.split("_")
        cat_type = parts[1]
        title_name = parts[2]
        ADMIN_STATES[user_id] = f"SHOP_PRICE_{title_name}_{cat_type}"
        await query.edit_message_text(f"💰 قیمت لقب « {title_name} » را برای قرارگیری در بخش **{CAT_NAMES[cat_type]}** به عدد وارد کنید:")
        return

    if data == "admin_home":
        keyboard = [
            [InlineKeyboardButton("📊 لیست کاربران", callback_data="admin_users"), InlineKeyboardButton("🏆 تالار مشاهیر", callback_data="admin_top")],
            [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"), InlineKeyboardButton("🔄 باز‌یابی پیام رنک", callback_data="admin_restore_msg")],
            [InlineKeyboardButton("🚀 ارتقا امتیاز دلخواه", callback_data="admin_set_score"), InlineKeyboardButton("🧹 صفر کردن امتیاز", callback_data="admin_reset_score")],
            [InlineKeyboardButton("➕ افزودن تگ جدید به شاپ", callback_data="admin_add_shop"), InlineKeyboardButton("🔑 ساخت ردیم کد", callback_data="admin_make_redeem")],
            [InlineKeyboardButton("📊 رهگیری آمار امتیازگیری", callback_data="admin_check_logs")],
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
            "🏆 **🏆 تالار مشاهیر و ۱۰ گلادیاتور برتر کلوب 🏆**\n\n"
            "👑 1. MSTVIOF\n  Rank: 🥇 Gold II | ⭐ 1847 XP\n\n"
            "⚡ 2. bardia790\n  Rank: 🥇 Gold I | ⭐ 1690 XP\n\n"
            "🛡️ 3. Meemahyar\n  Rank: 🥈 Silver III | ⭐ 905 XP\n\n"
            "🎖️ 4. aria2773\n  Rank: 🥉 Bronze I | ⭐ 0 XP\n\n"
            "📢 رنک‌های بالای ۷۰۰۰ و ۸۰۰۰ کاپ، سر ماه ریست شده و جوایز ویژه می‌گیرند!\n\n"
            "💡 *این پیام نمونه است. شما به عنوان ادمین می‌توانید هر پیامی که ساختار مشابه بالا دارد را بفرستید تا دیتابیس خودکار آپدیت شود.*"
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
    elif data == "admin_make_redeem":
        ADMIN_STATES[user_id] = "WAITING_FOR_REDEEM_CODE"
        await query.edit_message_text("🔑 لطفا کد کلمه‌ای ردیم کد مدنظرتان را ارسال کنید (مثلاً: ARIA2026):")
    elif data == "admin_check_logs":
        ADMIN_STATES[user_id] = "WAITING_FOR_LOGS_ID"
        await query.edit_message_text("📊 لطفا آیدی عددی (Telegram ID) کاربر مورد نظر را بفرستید تا ریز امتیازگیری‌اش نمایش داده شود:")
    elif data == "admin_close":
        await query.edit_message_text("🔒 پنل مدیریت بسته شد.")
        
    if user_id in ADMIN_STATES and ADMIN_STATES[user_id] == "WAITING_FOR_LOGS_ID":
        pass
    await query.answer()

async def handle_admin_logs_input(update: Update, user_id, text):
    try:
        target_id = int(text)
    except ValueError:
        await update.message.reply_text("❌ خطا! آیدی عددی نامعتبر است.")
        return
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    logs = cursor.execute('SELECT game_type, count FROM score_logs WHERE telegram_id = ?', (target_id,)).fetchall()
    conn.close()
    if not logs:
        await update.message.reply_text("📊 این کاربر هنوز هیچ لاگ و آماری در بخش امتیازگیری ثبت نکرده است.")
        return
    report = f"📊 **گزارش نحوه فعالیت و دریافت امتیاز آیدی `{target_id}`:**\n\n"
    for game_type, count in logs:
        gname = "🎲 تاس انفرادی" if game_type == "solo_roll" else "⚔️ نبرد دوئل"
        report += f"🔹 تعداد بازی در بخش {gname}: `{count}` بار\n"
    await update.message.reply_text(report, parse_mode="Markdown")

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
    application.add_handler(CommandHandler("redeem", redeem_command))

    application.add_handler(CallbackQueryHandler(handle_callbacks, pattern="^(pv_duel_start|pvduel_|gduel_)"))
    application.add_handler(CallbackQueryHandler(admin_buttons, pattern="^(admin_|setcat_)"))
    application.add_handler(CallbackQueryHandler(shop_callback, pattern="^(shopmain_|shopbuy_)"))
    
    async def mid_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message and update.message.text:
            uid = update.effective_user.id
            txt = update.message.text.strip()
            if uid in ADMIN_STATES and ADMIN_STATES[uid] == "WAITING_FOR_LOGS_ID":
                del ADMIN_STATES[uid]
                await handle_admin_logs_input(update, uid, txt)
                return
        await monitor_messages_and_inputs(update, context)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mid_filter))

    print("🚀 نسخه جدید ربات با متن استارت ارتقایافته فعال شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
