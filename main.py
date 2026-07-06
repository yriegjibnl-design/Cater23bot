import os
import random
import psycopg2
import logging
import asyncio
import re
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

# وارد کردن توابع اختصاصی مدیریت دیتابیس از فایل جانبی (بدون متغیر مرده DB_FILE)
from database import init_db, is_user_admin, get_or_create_user, update_stats, get_top_players, calculate_rank, get_db_connection

BOT_TOKEN = os.getenv("BOT_TOKEN", "8894117383:AAFGeDmC1lnY_LoFaah7zTAX7NjriIb2-Tc")
INITIAL_ADMIN_ID = int(os.getenv("ADMIN_ID", "7430881772"))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# راه‌اندازی اولیه دیتابیس پستگرس
init_db(INITIAL_ADMIN_ID)

def init_event_table():
    """این متد برای سازگاری کامل دیتابیس کماکان باقی‌مانده و جدول را روی Postgres مدیریت می‌کند"""
    pass

DICE_SCORES = {1: -5, 2: 5, 3: 10, 4: 15, 5: 25, 6: 40}
CAT_NAMES = {"normal": "لقب عادی", "epic": "لقب افسانه‌ای", "legendary": "لقب لجندری", "special": "👑 آیتم‌های ویژه شاپ"}

DICE_MOTIVATIONS = {
    6: ["🔥 **شــــــــــش ملوووووووک! میدان نبرد به آتش کشیده شد!**", "😎 شش چرخ روزگار به کامت چرخید! فوق‌العاده بود!"],
    5: ["⚡ **بسیار عالی! شانس با تو همراهه جنگجو!**", "💪 یک پرتاب قدرتمند و بی‌نقص!"],
    4: ["👍 **خوب و مطمئن! قدم به قدم به پیروزی نزدیک‌تر میشی.**", "🛡️ پرتابی محکم برای حفظ موقعیت!"],
    3: ["😐 **معمولی و متوسط... می‌تونست خیلی بهتر باشه!**", "💫 ششانس وسط زمین ایستاده, پرتاب بعدی رو محکم‌تر بزن!"],
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
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT * FROM active_event ORDER BY id DESC LIMIT 1")
    ev = cursor.fetchone()
    
    if not ev:
        cursor.close(); conn.close()
        return None
    
    end_time = datetime.strptime(ev['end_time'], "%Y-%m-%d %H:%M:%S")
    if datetime.now() > end_time:
        cursor.execute("DELETE FROM active_event")
        conn.commit()
        cursor.close(); conn.close()
        return None
    cursor.close(); conn.close()
    return ev

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username if user.username else user.first_name)
    
    # 🔗 بررسی ورود از طریق لینک اختصاصی دوعل غیابی
    if context.args and context.args[0].startswith("challenge_"):
        try:
            challenger_id = int(context.args[0].split("_")[1])
            if challenger_id == user.id:
                await update.message.reply_text("❌ دیوانه شدی؟ نمی‌توانی لینک دوئل خودت را استارت بزنی!")
                return
            
            keyboard = [[
                InlineKeyboardButton("🎲 قبول نبرد غیابی", callback_data=f"pvduel_yes_{challenger_id}_{user.id}"),
                InlineKeyboardButton("🏳️ لغو چالش", callback_data=f"pvduel_no_{challenger_id}_{user.id}")
            ]]
            await update.message.reply_markdown(f"⚔️ **شما توسط لینک اختصاصی به یک دوئل غیابی دعوت شدید!**\nآیا چالش را قبول می‌کنید؟", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        except:
            pass

    welcome_text = (
        f"⚔️ **به قلمرو خونین و بی‌رحم «نبرد تاس» خوش آمدی، {user.first_name}!** ⚔️\n\n"
        f"موتور ربات کاملاً کوبیده شده و به دیتابیس قدرتمند PostgreSQL متصل شده است! 🚀\n"
        f"دستت رو بذار روی دکمه، تاس رو پرتاب کن و ثابت کن شاهِ این میدونی یا فقط یه تماشاچی! 🔥"
    )
    
    ev = get_current_active_event()
    text_btn = "🕹️ بخش ایونت (فعال 🔥)" if ev else "🕹️ بخش ایونت"
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(text_btn, callback_data="user_check_event")]])
    
    await update.message.reply_markdown(welcome_text, reply_markup=get_main_menu_keyboard())
    await update.message.reply_text("✨ جهت بررسی رویدادها و چالش‌های زنده کلوب دکمه زیر را لمس کنید:", reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "⚔️ 🔴 **لیست فرمان‌های نبرد کلوب تاس (آپدیت غول)** 🔴 ⚔️\n\n"
        "🎲 `🎲 پرتاب تاس` — پرتاب تاس انفرادی (دارای شانس حمله بحرانی متوالی)\n"
        "⚔️ `/duel [راند] [مقدار شرط]` — **دوئل شرطی در گروه** (حداکثر ۶ راند، سقف شرط ۵۰ یا ۵۰۰ XP)\n"
        "🏪 `🏪 بازارچه لقب` — خرید دسته‌بندی‌شده لقب‌ها و آیتم‌های شاپ با امتیاز\n"
        "👤 `👤 پروفایل من` — نمایش کارت نبرد به همراه ویترین انتخاب لقب لایو\n"
        "🏆 `🏆 تالار افتخارات` — جدول مشاهیر و رنکینگ هاردکور اینفینیتی\n"
        "🔑 `/redeem [کد]` — فعال‌سازی کدهای هدیه ادمین\n"
    )
    if is_user_admin(update.effective_user.id): help_text += "\n⚙️ `/admin` — کنترل پنل اتاق فرماندهی"
    await update.message.reply_markdown(help_text, reply_markup=get_main_menu_keyboard())

def register_and_check_critical(telegram_id, current_dice):
    conn = get_db_connection(); cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO dice_history (telegram_id, dice_value, rolled_at) VALUES (%s, %s, %s)", (telegram_id, current_dice, now_str))
    
    cursor.execute('''
        SELECT dice_value FROM dice_history 
        WHERE telegram_id = %s 
        ORDER BY id DESC LIMIT 3
    ''', (telegram_id,))
    history = cursor.fetchall()
    
    is_critical = False
    if len(history) == 3:
        if history[0][0] == history[1][0] == history[2][0]:
            is_critical = True
            cursor.execute("DELETE FROM dice_history WHERE telegram_id = %s", (telegram_id,))
            
    conn.commit(); cursor.close(); conn.close()
    return is_critical

def log_score_source(telegram_id, game_type):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO score_logs (telegram_id, game_type, count) VALUES (%s, %s, 1)
        ON CONFLICT(telegram_id, game_type) DO UPDATE SET count = score_logs.count + 1
    ''', (telegram_id, game_type))
    conn.commit(); cursor.close(); conn.close()

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam_and_mute(update, "dice"): return
    user_id = update.effective_user.id
    user_data = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    title_tag = f" [{user_data['title']}]" if user_data['title'] != 'بدون لقب' else ""
    
    dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id)
    dice_value = dice_msg.dice.value
    
    # 🎲 بررسی قابلیت آیتم ویژه "تاس شانس" (اگر تاس ۱ آمد و آیتم خریداری شده بود)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT count FROM score_logs WHERE telegram_id = %s AND game_type = 'item_lucky_dice'", (user_id,))
    has_lucky_item = cursor.fetchone()
    
    # از کاپ ۱۰,۰۰۰ به بعد آیتم تاس شانس کاملاً غیرفعال می‌شود
    if dice_value == 1 and has_lucky_item and has_lucky_item[0] > 0 and user_data['score'] < 10000:
        await asyncio.sleep(2)
        await update.message.reply_markdown("🔮 **آیتم تاس شانس فعال شد!** چون عدد ۱ آوردی، سیستم خودکار تاس مجدد برات می‌ریزه!")
        dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id)
        dice_value = dice_msg.dice.value
        cursor.execute("UPDATE score_logs SET count = count - 1 WHERE telegram_id = %s AND game_type = 'item_lucky_dice'", (user_id,))
        conn.commit()
        
    cursor.close(); conn.close()
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
            ev_bonus_text = "\n🃏 **[ایونت تاس معکوس فعال است]**"

    is_critical = register_and_check_critical(user_id, dice_value)
    if is_critical:
        score_gained = (dice_value * 3) * 3 if not ev or ev['event_id'] != 1 else ((dice_value * 3) * 3) * 2
        motivation = f"⚡💥 **CRITICAL HIT! حمله بحرانی رخ داد!!!** 💥⚡"
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
        await update.message.reply_text(f"⏳ **کول‌داون سرور!** تا {left} ثانیه دیگر نمی‌توانی دوئل بزنی.")
        return

    p2_msg_id = update.message.reply_to_message.message_id
    p1_msg_id = update.message.message_id
    if p1.id == p2.id or p2.is_bot: return

    # 🛒 بررسی باز بودن محدودیت راندهای شاپ ویژه (تا ۲۰ راند)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT count FROM score_logs WHERE telegram_id = %s AND game_type = 'item_unlimited_duel'", (p1.id,))
    has_unlimited_rounds = cursor.fetchone()
    max_rounds = 20 if (has_unlimited_rounds and has_unlimited_rounds[0] > 0) else 6

    # 🛒 بررسی سقف شرط‌بندی شاپ ویژه (تا ۵۰۰ امتیاز)
    cursor.execute("SELECT count FROM score_logs WHERE telegram_id = %s AND game_type = 'item_high_wager'", (p1.id,))
    has_high_wager = cursor.fetchone()
    max_wager = 500 if (has_high_wager and has_high_wager[0] > 0) else 50
    cursor.close(); conn.close()

    rounds = 3
    wager = 0
    if context.args:
        try:
            rounds = int(context.args[0])
            if rounds < 1: rounds = 3
            if rounds > max_rounds: rounds = max_rounds
        except ValueError: pass
        
        if len(context.args) > 1:
            try:
                wager = int(context.args[1])
                if wager < 0: wager = 0
                if wager > max_wager:
                    await update.message.reply_text(f"❌ **خطا!** سقف شرط‌بندی مجاز شما حداکثر **{max_wager} امتیاز** است! (برای ارتقا به ۵۰۰، آیتم شاپ ویژه را بخرید)")
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

    wager_text = f"💰 **شرط نبرد:** {wager} XP (مجموعاً {wager * 2} کاپ در وسط زمین!)\n" if wager > 0 else ""
    keyboard = [[
        InlineKeyboardButton("⚔️ قبول می‌کنم", callback_data=f"gduel_yes_{p1.id}_{p2.id}_{rounds}_{p1_msg_id}_{p2_msg_id}_{wager}"),
        InlineKeyboardButton("🏳️ نه", callback_data=f"gduel_no_{p2.id}")
    ]]
    await update.message.reply_markdown(
        f"⚔️ **درخواست دوئل گروهی!**\n\n👤 **شروع‌کننده:** {p1_name}\n🎯 **حریف:** {p2_name}\n🏁 **راند:** {rounds}\n{wager_text}\nآیا چالش را قبول می‌کنی؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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
    
    leaderboard_text += "👑 *رنک اینفینیتی [GOD OF DICE] ابدی متعلق به ۱۰ نفر اول سقف ۱۴k کاپ است!*"
    keyboard = [[InlineKeyboardButton("🔥 لینک چالش اختصاصی (دوئل غیابی)", callback_data="pv_duel_start")]]
    
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
        rem_h = rem.seconds // 3600
        rem_m = (rem.seconds % 3600) // 60
        
        text = (
            f"🕹 *پنجره اطلاعات ایونت زنده کلوب* 🕹\n\n"
            f"🔥 *نام رویداد:* {ev['event_name']}\n"
            f"🎁 *پاداش نهایی ایونت:* {ev['reward_value'] if ev['reward_type'] != 'none' else 'جوایز سیستمی و دبل'}\n"
            f"⏳ *زمان باقی‌مانده:* {rem_h} ساعت و {rem_m} دقیقه"
        )
        await query.message.reply_text(text, parse_mode="Markdown")
        return

    # 🔥 ۱. قابلیت جهنمی: تولید لینک دعوت اختصاصی برای دوئل غیابی در پی‌وی
    if query.data == "pv_duel_start":
        await query.answer()
        bot_info = await context.bot.get_me()
        challenge_link = f"https://t.me/{bot_info.username}?start=challenge_{user_id}"
        
        share_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎯 ارسال لینک به حریف", url=f"https://t.me/share/url?url={challenge_link}&text=اگه%20خایه%20داری%20بیا%20روی%20این%20لینک%20کلیک%20کن%20تا%20توی%20کلوب%20تاس%20دوعل%20بزنیم!%20⚔️🎲")
        ]])
        await query.message.reply_markdown(
            f"🚀 **لینک دعوت اختصاصی شما ساخته شد!**\n\n`{challenge_link}`\n\n"
            f"این لینک رو برای هر حریفی بفرستی و روش کلیک کنه، چالش دوئل غیابی جفتتون استارت می‌خوره!",
            reply_markup=share_markup
        )
        return

    if data[0] == "pvduel":
        action = data[1]; p1_id = int(data[2]); p2_id = int(data[3])
        if user_id != p2_id:
            await query.answer("❌ این درخواست برای شما نیست!", show_alert=True); return
        if action == "no":
            await query.answer(); await query.edit_message_text("🏳️ چالش رد شد.")
            return
        if action == "yes":
            await query.answer(); await query.edit_message_text("⚔️ **دوئل غیابی آغاز شد! پرتاب تاس‌ها...**")
            
            conn = get_db_connection(); cursor = conn.cursor()
            cursor.execute('SELECT username FROM users WHERE telegram_id = %s', (p1_id,))
            p1_row = cursor.fetchone()
            cursor.execute('SELECT username FROM users WHERE telegram_id = %s', (p2_id,))
            p2_row = cursor.fetchone()
            p1_name = p1_row['username'] if p1_row else "حریف"
            p2_name = p2_row['username'] if p2_row else "تو"
            cursor.close(); conn.close()

            p1_total, p2_total = 0, 0
            for _ in range(3):
                d_msg = await context.bot.send_dice(chat_id=chat_id)
                p1_total += d_msg.dice.value
                await asyncio.sleep(0.5)
            await asyncio.sleep(2)
            
            for _ in range(3):
                d_msg = await context.bot.send_dice(chat_id=chat_id)
                p2_total += d_msg.dice.value
                await asyncio.sleep(0.5)
            await asyncio.sleep(2)

            win_xp, lose_xp = 40, 5
            summary = f"📊 **نتیجه نهایی چالش غیابی:**\n\n👤 {p1_name}: `{p1_total}`\n👤 {p2_name}: `{p2_total}`\n\n"

            if p1_total > p2_total:
                res = summary + f"🏆 برنده: {p1_name} (+{win_xp} XP)"
                update_stats(p1_id, win_xp, 'win'); update_stats(p2_id, lose_xp, 'loss')
            elif p2_total > p1_total:
                res = summary + f"🏆 برنده: {p2_name} (+{win_xp} XP)"
                update_stats(p2_id, win_xp, 'win'); update_stats(p1_id, lose_xp, 'loss')
            else:
                res = summary + "🤝 نتیجه مساوی شد!"
                update_stats(p1_id, 0, 'draw'); update_stats(p2_id, 0, 'draw')

            await context.bot.send_message(chat_id=chat_id, text=res)
            try: await context.bot.send_message(chat_id=p1_id, text=f"🏁 نتیجه دوئل غیابی شما مشخص شد:\n\n{res}")
            except: pass
            return

    if data[0] == "gduel":
        action = data[1]
        if action == "no":
            if user_id != int(data[2]): return
            await query.answer(); await query.edit_message_text(f"🏳️ دوئل توسط حریف لغو شد.")
            return
        if action == "yes":
            p1_id, p2_id, rounds = int(data[2]), int(data[3]), int(data[4])
            p1_msg_id, p2_msg_id = int(data[5]), int(data[6])
            wager = int(data[7]) if len(data) > 7 else 0
            
            if user_id != p2_id: 
                await query.answer("❌ درخواست مال شما نیست!", show_alert=True); return
            
            conn = get_db_connection(); cursor = conn.cursor()
            p1_chk = cursor.execute('SELECT score, username FROM users WHERE telegram_id = %s', (p1_id,)).fetchone()
            p2_chk = cursor.execute('SELECT score, username FROM users WHERE telegram_id = %s', (p2_id,)).fetchone()
            
            if wager > 0:
                if not p1_chk or p1_chk['score'] < wager or not p2_chk or p2_chk['score'] < wager:
                    await query.answer("❌ موجودی کمه سرمایه!", show_alert=True); cursor.close(); conn.close(); return
            
            await query.answer(); await query.edit_message_text("⚔️ **نبرد تایید شد! شروع بازی...**")
            p1_name = p1_chk['username']; p2_name = p2_chk['username']
            cursor.close(); conn.close()

            p1_total, p2_total = 0, 0
            await context.bot.send_message(chat_id=chat_id, text=f"🎲 **پرتاب تاس برای: {p1_name}**")
            for _ in range(rounds):
                d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p1_msg_id)
                p1_total += d.dice.value
                await asyncio.sleep(2.5)
            
            await context.bot.send_message(chat_id=chat_id, text=f"🎲 **پرتاب تاس برای: {p2_name}**")
            for _ in range(rounds):
                d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p2_msg_id)
                p2_total += d.dice.value
                await asyncio.sleep(2.5)

            win_xp, lose_xp = 40, 5
            result_text = f"🏁 **نتیجه نهایی دوئل:**\n\n👤 {p1_name}: {p1_total}\n👤 {p2_name}: {p2_total}\n\n"

            if p1_total > p2_total:
                total_win = win_xp + wager
                total_lose = lose_xp - wager
                result_text += f"🏆 **برنده: {p1_name} (+{total_win} XP)**"
                update_stats(p1_id, total_win, 'win'); update_stats(p2_id, total_lose, 'loss')
            elif p2_total > p1_total:
                total_win = win_xp + wager
                total_lose = lose_xp - wager
                result_text += f"🏆 **برنده: {p2_name} (+{total_win} XP)**"
                update_stats(p2_id, total_win, 'win'); update_stats(p1_id, total_lose, 'loss')
            else:
                result_text += f"🤝 **نتیجه مساوی!**"
                update_stats(p1_id, 0, 'draw'); update_stats(p2_id, 0, 'draw')
            
            DUEL_COOLDOWNS[p1_id] = datetime.now().timestamp() + 15.0
            DUEL_COOLDOWNS[p2_id] = datetime.now().timestamp() + 15.0
            await context.bot.send_message(chat_id=chat_id, text=result_text)

    # 🎭 ۴. قابلیت ویترین انتخاب لقب به صورت لایو از طریق کلیک روی دکمه شیشه‌ای پروفایل
    if data[0] == "titleview":
        await query.answer()
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("SELECT code, title_name FROM redeem_codes")
        all_titles = cursor.fetchall()
        cursor.execute("SELECT title_name FROM shop")
        all_titles += cursor.fetchall()
        
        # حذف تگ‌های تکراری
        unique_titles = list(set([t['title_name'] for t in all_titles]))
        
        cursor.execute("SELECT code FROM redeem_history WHERE telegram_id = %s", (user_id,))
        used_codes = [r['code'] for r in cursor.fetchall()]
        
        unlocked = []
        for t in unique_titles:
            cursor.execute("SELECT 1 FROM redeem_codes WHERE title_name = %s AND code = ANY(%s)", (t, used_codes))
            is_redeemed = cursor.fetchone()
            cursor.execute("SELECT 1 FROM score_logs WHERE telegram_id = %s AND game_type = %s", (user_id, f"bought_title_{t}"))
            is_bought = cursor.fetchone()
            if is_redeemed or is_bought:
                unlocked.append(t)
                
        kb = []
        for ut in unique_titles:
            if ut in unlocked:
                kb.append([InlineKeyboardButton(f"✅ {ut} (فعال کردن)", callback_data=f"settitle_now_{ut}")])
            else:
                kb.append([InlineKeyboardButton(f"🔒 {ut} (قفل)", callback_data="title_is_locked")])
        
        kb.append([InlineKeyboardButton("🔙 بازگشت به پروفایل", callback_data="back_to_prof")])
        await query.edit_message_text("🎭 **ویترین لقب‌های شما:**\nلقب‌هایی که باز کردی رو تیک بزن تا روی کارتن نبردت فعال بشن:", reply_markup=InlineKeyboardMarkup(kb))
        cursor.close(); conn.close()
        return

    if data[0] == "settitle_now":
        t_name = data[2]
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("UPDATE users SET title = %s WHERE telegram_id = %s", (t_name, user_id))
        conn.commit(); cursor.close(); conn.close()
        await query.answer(f"👑 لقب {t_name} با موفقیت فعال شد!", show_alert=True)
        await profile_command(update, context)
        return
        
    if data[0] == "title" and data[1] == "is" and data[2] == "locked":
        await query.answer("❌ این لقب قفله مشتی! باید توی شاپ بخریش یا ردیم‌کدش رو بزنی!", show_alert=True)
        return
        
    if data[0] == "back" and data[1] == "to" and data[2] == "prof":
        await query.answer()
        await profile_command(update, context)
        return

    if data[0] == "admin": await admin_buttons(update, context)
    if data[0] == "shop": await shop_callback(update, context)

async def monitor_messages_and_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
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

    if user_id in ADMIN_STATES:
        state = ADMIN_STATES[user_id]
        if state.startswith("EV_GET_DICE_"):
            ev_id = int(state.split("_")[2])
            ADMIN_STATES[user_id] = f"EV_GET_HOURS_{ev_id}_{text}"
            await update.message.reply_text("🕒 حالا مدت زمان این رویداد را به ساعت وارد کنید:")
            return
        elif state.startswith("EV_GET_DISCOUNT_"):
            ev_id = int(state.split("_")[3])
            ADMIN_STATES[user_id] = f"EV_GET_HOURS_{ev_id}_{text}"
            await update.message.reply_text("🕒 حالا مدت زمان این رویداد را به ساعت وارد کنید:")
            return
        elif state.startswith("EV_GET_HOURS_"):
            parts = state.split("_")
            ev_id = int(parts[3])
            param = parts[4]
            await finalize_and_broadcast_event(update, context, ev_id, float(text), param, "none", "")
            return
        elif state == "WAITING_FOR_BROADCAST":
            del ADMIN_STATES[user_id]
            conn = get_db_connection(); cursor = conn.cursor()
            cursor.execute('SELECT telegram_id FROM users')
            rows = cursor.fetchall(); cursor.close(); conn.close()
            for row in rows:
                try: await context.bot.send_message(chat_id=row['telegram_id'], text=f"📢 **اطلاعیه مدیریت:**\n\n{text}", parse_mode="Markdown")
                except: continue
            await update.message.reply_text("✅ فرستاده شد.")
            return

async def finalize_and_broadcast_event(update, context, ev_id, hours, param, rew_type, rew_val):
    admin_id = update.effective_user.id
    if admin_id in ADMIN_STATES: del ADMIN_STATES[admin_id]
    
    end_time = datetime.now() + timedelta(hours=hours)
    end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    
    ex_data = {}
    if ev_id == 2: ex_data["dice"] = param
    if ev_id == 15: ex_data["discount"] = param
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("DELETE FROM active_event")
    cursor.execute("""
        INSERT INTO active_event (event_id, event_name, end_time, extra_data, reward_type, reward_value)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (ev_id, EVENT_NAMES_LIST[ev_id], end_time_str, json.dumps(ex_data), rew_type, rew_val))
    
    cursor.execute("SELECT telegram_id FROM users")
    users = cursor.fetchall()
    conn.commit(); cursor.close(); conn.close()
    
    msg_broadcast = (
        f"🚨 **رویداد جدید کلوب آغاز شد!** 🚨\n\n"
        f"🎯 **ایونت:** {EVENT_NAMES_LIST[ev_id]}\n"
        f"🕒 **مدت زمان رویداد:** {hours} ساعت\n\n"
        f" جهت مشاهده قوانین زنده روی دکمه زیر بزنید! 👇"
    )
    broadcast_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🕹️ جزئیات رویداد زنده", callback_data="user_check_event")]])
    
    for u in users:
        try: await context.bot.send_message(chat_id=u['telegram_id'], text=msg_broadcast, reply_markup=broadcast_markup, parse_mode="Markdown")
        except: continue

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id
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
    
    kb = [[InlineKeyboardButton("👑 ویترین انتخاب لقب", callback_data="titleview_root")]]
    markup = InlineKeyboardMarkup(kb)
    
    if query:
        await query.edit_message_text(profile_text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_markdown(profile_text, reply_markup=markup)
    return profile_text

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    keyboard = [[InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal")],
                [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
                [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")],
                [InlineKeyboardButton("🛒 خرید آیتم‌های ویژه شاپ (XP)", callback_data="shopmain_cat_special")]]
    if update.message:
        await update.message.reply_text(f"🏪 **به بازارچه لقب‌ها خوش آمدی!**\n💰 موجودی: {user['score']} XP\n\nانتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = query.from_user.id; data = query.data
    await query.answer()
    
    if data.startswith("shopmain_cat_"):
        cat_type = data.replace("shopmain_cat_", "")
        
        # ⚔️ ۲. منطق اعمال تخفیف خودکار ایونت جمعه سیاه در شاپ
        ev = get_current_active_event()
        discount_pct = 0
        if ev and ev['event_id'] == 15:
            discount_pct = int(json.loads(ev['extra_data']).get('discount', 0))

        keyboard = []
        if cat_type == "special":
            # آیتم‌های ویژه جدید با XP
            items = [
                ("item_unlimited_duel", "🔹 دوعل بدون محدودیت (تا ۲۰ راند)", 1200),
                ("item_high_wager", "🔹 شرط‌بندی بیشتر (تا سقف ۵۰۰)", 2000),
                ("item_lucky_dice", "🔹 تاس شانس (شروع مجدد روی عدد ۱)", 3500)
            ]
            for internal_name, label, cost in items:
                final_cost = int(cost * (100 - discount_pct) / 100) if discount_pct > 0 else cost
                keyboard.append([InlineKeyboardButton(f"{label} 💰 {final_cost} XP", callback_data=f"shopbuy_special_{internal_name}_{final_cost}")])
        else:
            conn = get_db_connection(); cursor = conn.cursor()
            cursor.execute("SELECT id, title_name, cost FROM shop WHERE category = %s", (cat_type,))
            shop_items = cursor.fetchall(); cursor.close(); conn.close()
            for item in shop_items:
                final_cost = int(item['cost'] * (100 - discount_pct) / 100) if discount_pct > 0 else item['cost']
                keyboard.append([InlineKeyboardButton(f"{item['title_name']} 💰 {final_cost} XP", callback_data=f"shopbuy_id_{item['id']}_{final_cost}")])
                
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shopmain_back")])
        await query.edit_message_text(f"🛍️ لیست بخش: {CAT_NAMES[cat_type]}", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "shopmain_back":
        keyboard = [[InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal")],
                    [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
                    [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")],
                    [InlineKeyboardButton("🛒 خرید آیتم‌های ویژه شاپ (XP)", callback_data="shopmain_cat_special")]]
        await query.edit_message_text("🏪 **بازارچه لقب‌ها**", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data.startswith("shopbuy_special_"):
        parts = data.split("_")
        item_name = parts[2] + "_" + parts[3]
        final_cost = int(parts[4])
        
        user = get_or_create_user(user_id, query.from_user.username)
        if user['score'] < final_cost:
            await query.message.reply_text("❌ امتیاز کافی نداری مشتی!"); return
            
        update_stats(user_id, -final_cost, 'loss')
        log_score_source(user_id, item_name) # ذخیره فعال بودن آیتم در تاریخچه لاگ‌ها
        await query.edit_message_text("🎉 آیتم ویژه با موفقیت فعال شد و روی حساب شما اعمال گردید!")

    elif data.startswith("shopbuy_id_"):
        parts = data.split("_")
        item_id = int(parts[2])
        final_cost = int(parts[3])
        
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("SELECT * FROM shop WHERE id = %s", (item_id,))
        item = cursor.fetchone()
        
        user = get_or_create_user(user_id, query.from_user.username)
        if user['score'] < final_cost:
            await query.message.reply_text("❌ امتیاز کافی نداری مشتی!"); cursor.close(); conn.close(); return
            
        cursor.execute('UPDATE users SET score = score - %s, title = %s WHERE telegram_id = %s', (final_cost, item['title_name'], user_id))
        cursor.execute("INSERT INTO score_logs (telegram_id, game_type, count) VALUES (%s, %s, 1) ON CONFLICT(telegram_id, game_type) DO NOTHING", (user_id, f"bought_title_{item['title_name']}"))
        conn.commit(); cursor.close(); conn.close()
        await query.edit_message_text(f"🎉 تگ ویژه « {item['title_name']} » فعال شد!")

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = context.args[0].strip() if context.args else update.message.text.replace("/redeem ", "").strip()
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT * FROM redeem_codes WHERE code = %s', (code,))
    cdata = cursor.fetchone()
    
    if not cdata or cdata['current_uses'] >= cdata['max_uses']:
        await update.message.reply_text("❌ کد معتبر نیست یا تمام شده."); cursor.close(); conn.close(); return
        
    cursor.execute('INSERT INTO redeem_history (telegram_id, code, used_at) VALUES (%s, %s, %s)', (user_id, code, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    cursor.execute('UPDATE redeem_codes SET current_uses = current_uses + 1 WHERE code = %s', (code,))
    cursor.execute('UPDATE users SET title = %s WHERE telegram_id = %s', (cdata['title_name'], user_id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🎉 کد هدیه فعال شد و لقب موقت **{cdata['title_name']}** اعطا گردید.")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_user_admin(update.effective_user.id): return
    keyboard = [
        [InlineKeyboardButton("📢 پیام همگانی ادمین", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🕹️ مدیریت پیشرفته ایونت‌ها", callback_data="admin_events_root")],
        [InlineKeyboardButton("❌ بستن پنل", callback_data="admin_close")]
    ]
    await update.message.reply_text("🛠 **اتاق فرمان مدیریت پیشرفته ربات (نسخه جدید):**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = query.from_user.id; data = query.data
    if data == "admin_events_root":
        kb = []
        for ev_id, ev_name in EVENT_NAMES_LIST.items():
            kb.append([InlineKeyboardButton(ev_name, callback_data=f"ev_manage_{ev_id}")])
        await query.edit_message_text("🕹️ **منوی تنظیمات ایونت‌ها:**", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("ev_manage_"):
        ev_id = int(data.split("_")[2])
        if ev_id == 15:
            ADMIN_STATES[user_id] = f"EV_GET_DISCOUNT_{ev_id}"
            await query.edit_message_text("💰 درصد تخفیف شاپ جمعه سیاه را به عدد وارد کن (مثلاً 45):")
        else:
            ADMIN_STATES[user_id] = f"EV_GET_HOURS_{ev_id}_0"
            await query.edit_message_text("🕒 مدت زمان ایونت را به ساعت وارد کنید:")
    elif data == "admin_broadcast":
        ADMIN_STATES[user_id] = "WAITING_FOR_BROADCAST"
        await query.edit_message_text("📢 متن پیام همگانی خود را ارسال کنید:")
    elif data == "admin_close":
        await query.edit_message_text("🔒 بسته شد.")
    await query.answer()

def main():
    application = Application.builder().token(BOT_TOKEN).job_queue(None).build()

    application.add_application_init_callback(lambda app: init_db(INITIAL_ADMIN_ID))

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("dice", dice_command))
    application.add_handler(CommandHandler("duel", duel_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("top", top_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("shop", shop_command))
    application.add_handler(CommandHandler("redeem", redeem_command))

    application.add_handler(CallbackQueryHandler(handle_callbacks, pattern="^(pv_duel_start|pvduel_|gduel_|user_check_event|titleview|settitle_now|back_to_prof)"))
    application.add_handler(CallbackQueryHandler(admin_buttons, pattern="^(admin_|ev_)"))
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

    print("🚀 ربات با موفقیت روی سرور PostgreSQL ران شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
