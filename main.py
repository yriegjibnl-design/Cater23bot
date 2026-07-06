import os
import random
import psycopg2
from psycopg2.extras import DictCursor
import logging
import asyncio
import re
import json
import uuid
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

from database import init_db, is_user_admin, get_or_create_user, update_stats, get_top_players, calculate_rank, get_db_connection

BOT_TOKEN = os.getenv("BOT_TOKEN", "8894117383:AAFqv00G_eAFkeP0x-UhrENKByEb5U5_MnM")
INITIAL_ADMIN_ID = int(os.getenv("ADMIN_ID", "7430881772"))

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

init_db(INITIAL_ADMIN_ID)

DICE_SCORES = {1: -5, 2: 5, 3: 10, 4: 15, 5: 25, 6: 40}
CAT_NAMES = {"normal": "لقب عادی", "epic": "لقب افسانه‌ای", "legendary": "لقب لجندری", "utility": "آیتم‌های کاربردی ویژه"}

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
TEMP_DICE_REROLL = {} # ذخیره وضعیت تاس شانس برای ران بعدی

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
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM active_event ORDER BY id DESC LIMIT 1")
    ev = cursor.fetchone()
    conn.close()
    if not ev: return None
    
    end_time = datetime.strptime(ev['end_time'], "%Y-%m-%d %H:%M:%S")
    if datetime.now() > end_time:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM active_event")
        conn.commit()
        conn.close()
        return None
    return ev

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username if user.username else user.first_name)
    
    # ثبت لینک چلنج غیابی در صورت وجود پارامتر ورودی استارت
    if context.args and context.args[0].startswith("chal"):
        challenge_id = context.args[0]
        await handle_offline_challenge_join(update, context, challenge_id)
        return

    welcome_text = (
        f"⚔️ **به قلمرو خونین و بی‌رحم «نبرد تاس» خوش آمدی، {user.first_name}!** ⚔️\n\n"
        f"اینجا کلوپ گلادیاتورهاست؛ جایی که شانس فقط به شجاع‌ها رو می‌کنه! 🔥"
    )
    ev = get_current_active_event()
    text_btn = "🕹️ بخش ایونت (فعال 🔥)" if ev else "🕹️ بخش ایونت"
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(text_btn, callback_data="user_check_event")]])
    await update.message.reply_markdown(welcome_text, reply_markup=get_main_menu_keyboard())
    await update.message.reply_text("✨ جهت بررسی رویدادها دکمه زیر را لمس کنید:", reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "⚔️ 🔴 **لیست فرمان‌های نبرد کلوب تاس (آپدیت بزرگ اینفینیتی)** 🔴 ⚔️\n\n"
        "🎲 `🎲 پرتاب تاس` — پرتاب تاس انفرادی\n"
        "⚔️ `/duel [راند] [مقدار شرط]` — دوئل شرطی در گروه\n"
        "📨 `/challenge [آیدی_عددی_حریف] [راند] [شرط]` — ایجاد لینک چلنج غیابی اختصاصی\n"
        "🏪 `🏪 بازارچه لقب` — خرید انواع تگ، لقب و آیتم‌های کاربردی جدید\n"
        "👤 `👤 پروفایل من` — نمایش کارنامه جنگی و مدیریت تگ‌ها\n"
        "🏆 `🏆 تالار افتخارات` — جدول مشاهیر و رنکینگ هاردکور\n"
        "🔑 `/redeem [کد]` — فعال‌سازی کدهای هدیه\n"
    )
    if is_user_admin(update.effective_user.id): help_text += "\n⚙️ `/admin` — کنترل پنل اتاق فرماندهی"
    await update.message.reply_markdown(help_text, reply_markup=get_main_menu_keyboard())

def register_and_check_critical(telegram_id, current_dice):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO dice_history (telegram_id, dice_value, rolled_at) VALUES (%s, %s, %s)", (telegram_id, current_dice, now_str))
    cursor.execute("SELECT dice_value FROM dice_history WHERE telegram_id = %s ORDER BY rolled_at DESC LIMIT 3", (telegram_id,))
    history = cursor.fetchall()
    
    is_critical = False
    if len(history) == 3:
        if history[0][0] == history[1][0] == history[2][0]:
            is_critical = True
            cursor.execute("DELETE FROM dice_history WHERE telegram_id = %s", (telegram_id,))
    conn.commit()
    conn.close()
    return is_critical

def log_score_source(telegram_id, game_type):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO score_logs (telegram_id, game_type, count) VALUES (%s, %s, 1)
        ON CONFLICT(telegram_id, game_type) DO UPDATE SET count = score_logs.count + 1
    """, (telegram_id, game_type))
    conn.commit()
    conn.close()

def get_user_item_count(telegram_id, item_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT quantity FROM user_items WHERE telegram_id = %s AND item_id = %s", (telegram_id, item_id))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else 0

def use_one_item(telegram_id, item_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE user_items SET quantity = quantity - 1 WHERE telegram_id = %s AND item_id = %s", (telegram_id, item_id))
    conn.commit()
    conn.close()

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam_and_mute(update, "dice"): return
    user_id = update.effective_user.id
    user_data = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    title_tag = f" [{user_data['title']}]" if user_data['title'] != 'بدون لقب' else ""
    
    dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id)
    dice_value = dice_msg.dice.value
    await asyncio.sleep(3)
    
    # 💥 بررسی قابلیت ۲: مصرف آیتم تاس شانس (فقط برای سطوح زیر ۱۰,۰۰۰ امتیاز)
    if dice_value == 1 and user_data['score'] < 10000:
        lucky_count = get_user_item_count(user_id, "lucky_dice")
        if lucky_count > 0:
            use_one_item(user_id, "lucky_dice")
            await update.message.reply_markdown("🔮 **آیتم تاس شانس مصرف شد!** عدد ۱ آوردید اما شانس مجدد به شما اعطا گردید. چرخ دنده‌ها دوباره می‌چرخند...")
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

# ==========================================
# سیستم دوئل گروهی (با پشتیبانی از سقف آیتم‌ها)
# ==========================================
async def duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam_and_mute(update, "duel"): return
    p1 = update.effective_user
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ برای شروع دوئل گروهی، باید این دستور را روی پیام حریف ریپلای کنید!")
        return

    p2 = update.message.reply_to_message.from_user
    if p1.id == p2.id or p2.is_bot: return

    rounds = 3
    wager = 0
    
    p1_data = get_or_create_user(p1.id, p1.username if p1.username else p1.first_name)
    p2_data = get_or_create_user(p2.id, p2.username if p2.username else p2.first_name)

    if context.args:
        try:
            rounds = int(context.args[0])
            if rounds < 1: rounds = 3
            # 💥 بررسی قابلیت ۲: مصرف آپگرید راند دوعل تا ۲۰ راند
            if rounds > 6:
                if get_user_item_count(p1.id, "unlimited_duel") > 0:
                    if rounds > 20: rounds = 20
                    use_one_item(p1.id, "unlimited_duel")
                    await update.message.reply_text("🔮 آیتم ویژه «دوئل بدون محدودیت» مصرف شد و سقف راندها باز گردید!")
                else:
                    rounds = 6
                    await update.message.reply_text("⚠️ سقف مجاز راندها برای شما ۶ است. برای افزایش تا ۲۰ راند، آیتم آن را از شاپ تهیه کنید.")
        except ValueError: pass
        
        if len(context.args) > 1:
            try:
                wager = int(context.args[1])
                if wager < 0: wager = 0
                
                # 💥 بررسی قابلیت ۲: لیمیت شرط بندی تا ۵۰۰ کاپ
                max_wager_allowed = 50
                if get_user_item_count(p1.id, "high_wager") > 0:
                    max_wager_allowed = 500
                    use_one_item(p1.id, "high_wager")
                    await update.message.reply_text("🔮 آیتم ویژه «شرط‌بندی بیشتر» مصرف شد. سقف شرط این راند تا ۵۰۰ امتیاز افزایش یافت!")
                
                if wager > max_wager_allowed:
                    await update.message.reply_text(f"❌ سقف شرط‌بندی مجاز شما حداکثر {max_wager_allowed} امتیاز است!")
                    return
            except ValueError: pass

    if wager > 0:
        if p1_data['score'] < wager or p2_data['score'] < wager:
            await update.message.reply_text("❌ موجودی امتیاز یکی از طرفین کافی نیست!")
            return

    wager_text = f"💰 **شرط نبرد:** {wager} XP\n" if wager > 0 else ""
    keyboard = [[
        InlineKeyboardButton("⚔️ قبول می‌کنم", callback_data=f"gduel_yes_{p1.id}_{p2.id}_{rounds}_{update.message.message_id}_{update.message.reply_to_message.message_id}_{wager}"),
        InlineKeyboardButton("🏳️ نه", callback_data=f"gduel_no_{p2.id}")
    ]]
    await update.message.reply_markdown(
        f"⚔️ **درخواست دوئل گروهی!**\n\n👤 **شروع‌کننده:** {p1_data['username']}\n🎯 **حریف:** {p2_data['username']}\n🏁 **راند:** {rounds}\n{wager_text}آیا چالش را قبول می‌کنی؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==========================================
# 💥 قابلیت ۱: سیستم نبرد و لینک چلنج غیابی (Offline Challenges)
# ==========================================
async def challenge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("❌ این دستور را فقط در پیوی ربات برای فرستادن لینک چلنج غیابی استفاده کنید!")
        return
        
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("❌ فرمت صحیح: `/challenge [آیدی_عددی_حریف] [راندها] [مقدار_شرط]`")
        return
        
    try:
        target_id = int(context.args[0])
        rounds = int(context.args[1]) if len(context.args) > 1 else 3
        wager = int(context.args[2]) if len(context.args) > 2 else 0
    except ValueError:
        await update.message.reply_text("❌ پارامترها باید به صورت عددی وارد شوند.")
        return
        
    creator_id = update.effective_user.id
    if creator_id == target_id: return
    
    c_data = get_or_create_user(creator_id, update.effective_user.username)
    if wager > c_data['score']:
        await update.message.reply_text("❌ موجودی امتیاز شما کمتر از مقدار شرط است!")
        return

    challenge_id = f"chal_{uuid.uuid4().hex[:8]}"
    
    # پرتاب تاس غیابی بازیکن اول (سازنده لینک) به تعداد راندها
    total_creator_score = sum([random.randint(1, 6) for _ in range(rounds)])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO offline_challenges (challenge_id, creator_id, target_id, wager, rounds, creator_score, status, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s)
    """, (challenge_id, creator_id, target_id, wager, rounds, total_creator_score, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    bot_obj = await context.bot.get_me()
    invite_link = f"https://t.me/{bot_obj.username}?start={challenge_id}"
    
    await update.message.reply_markdown(
        f"📦 **لینک چلنج غیابی اختصاصی با موفقیت تولید شد!**\n\n"
        f"🏁 راندها: {rounds}\n"
        f"💰 شرط: {wager} XP\n"
        f"تاس‌های شما به صورت مخفی ریخته شد! لینک زیر را برای حریفتان بفرستید تا هر وقت آنلاین شد نبرد را کامل کند:\n\n🔗 {invite_link}"
    )

async def handle_offline_challenge_join(update: Update, context: ContextTypes.DEFAULT_TYPE, challenge_id: str):
    user_id = update.effective_user.id
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM offline_challenges WHERE challenge_id = %s", (challenge_id,))
    chal = cursor.fetchone()
    
    if not chal:
        await update.message.reply_text("❌ این لینک چلنج وجود ندارد یا منقضی شده است.")
        conn.close()
        return
        
    if chal['status'] != 'pending':
        await update.message.reply_text("❌ این مبارزه قبلاً به پایان رسیده است!")
        conn.close()
        return
        
    if chal['target_id'] != user_id:
        await update.message.reply_text("❌ این لینک نبرد غیابی اختصاصی است و برای شما صادر نشده است!")
        conn.close()
        return
        
    p2_data = get_or_create_user(user_id, update.effective_user.username)
    if chal['wager'] > p2_data['score']:
        await update.message.reply_text("❌ امتیاز شما برای قبول این چالش و شرط‌بندی کافی نیست!")
        conn.close()
        return
        
    # ریختن تاس‌های حریف (بازیکن دوم)
    rounds = chal['rounds']
    total_target_score = sum([random.randint(1, 6) for _ in range(rounds)])
    
    p1_id = chal['creator_id']
    p1_score = chal['creator_score']
    p2_score = total_target_score
    wager = chal['wager']
    
    cursor.execute("UPDATE offline_challenges SET status = 'completed' WHERE challenge_id = %s", (challenge_id,))
    conn.commit()
    conn.close()
    
    # ثبت نتایج نهایی هاردکور
    win_xp, lose_xp = 40, 5
    result_text = f"🏁 **نتیجه نهایی چالش غیابی:**\n\n"
    
    if p1_score > p2_score:
        res1 = win_xp + wager; res2 = lose_xp - wager
        update_stats(p1_id, res1, 'win'); update_stats(user_id, res2, 'loss')
        result_text += f"🏆 برنده غیابی: بازیکن اول با مجموع تاس {p1_score}\n💀 شما با مجموع تاس {p2_score} شکست خوردید! ({res2} XP)"
        try: await context.bot.send_message(chat_id=p1_id, text=f"🎉 حریف شما لینک چلنج غیابی را استارت زد! شما با مجموع تاس {p1_score} در برابر {p2_score} پیروز شدید! (+{res1} XP)")
        except: pass
    elif p2_score > p1_score:
        res1 = win_xp + wager; res2 = lose_xp - wager
        update_stats(user_id, res1, 'win'); update_stats(p1_id, res2, 'loss')
        result_text += f"🏆 شما با مجموع تاس {p2_score} در برابر {p1_score} پیروز شدید! (+{res1} XP)"
        try: await context.bot.send_message(chat_id=p1_id, text=f"💀 حریف لینک چلنج غیابی را استارت زد و با مجموع تاس {p2_score} در برابر {p1_score} شما را شکست داد! ({res2} XP)")
        except: pass
    else:
        update_stats(p1_id, 0, 'draw'); update_stats(user_id, 0, 'draw')
        result_text += f"🤝 نبرد غیابی با مجموع تاس‌های مساوی {p1_score} بر {p2_score} به تعادل رسید!"
        try: await context.bot.send_message(chat_id=p1_id, text=f"🤝 چالش غیابی شما با حریف با مجموع تاس {p1_score} مساوی شد.")
        except: pass
        
    await update.message.reply_markdown(result_text)

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
        medals = "👑" if "Infinity" in player['rank'] else "⚡" if index == 1 else "🛡️" if index == 2 else "🎖️"
        title_tag = f" ({player['title']})" if player['title'] != 'بدون لقب' else ""
        leaderboard_text += f"{medals} {index + 1}. **{player['username']}**{title_tag}\n  Rank: {player['rank']} | ⭐ {player['score']} XP\n\n"
    
    leaderboard_text += "📢 *۱۰ نفر برتر بالای ۱۴,۰۰۰ امتیاز به رنک جهنمی Infinity دست می‌یابند!*"
    keyboard = [[InlineKeyboardButton("⚔️ دوئل با برترین‌ها (مخصوص پیوی)", callback_data="pv_duel_start")]]
    if update.message:
        await update.message.reply_markdown(leaderboard_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return leaderboard_text, keyboard

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; data = query.data.split("_"); user_id = query.from_user.id
    
    if query.data == "user_check_event":
        ev = get_current_active_event()
        if not ev:
            await query.answer("❌ در حال حاضر هیچ ایونتی فعال نیست.", show_alert=True); return
        await query.answer()
        end_time = datetime.strptime(ev['end_time'], "%Y-%m-%d %H:%M:%S")
        rem = end_time - datetime.now()
        text = f"🕹️ **پنجره اطلاعات ایونت زنده کلوب**\n\n🔥 **نام رویداد:** {ev['event_name']}\n⏳ **پایان:** {rem.seconds // 3600} ساعت"
        await query.message.reply_text(text, parse_mode="Markdown")
        return

    if query.data == "pv_duel_start":
        await query.answer()
        PV_DUEL_STATES[user_id] = "WAITING_FOR_TARGET_NUMBER"
        await query.message.reply_text("🎯 **لطفاً شماره بازیکن مورد نظر خود را از لیست بالا وارد کنید:**")
        return

    if data[0] == "gduel" and data[1] == "yes":
        p1_id, p2_id, rounds = int(data[2]), int(data[3]), int(data[4])
        p1_msg_id, p2_msg_id = int(data[5]), int(data[6])
        wager = int(data[7]) if len(data) > 7 else 0
        
        if user_id != p2_id: 
            await query.answer("❌ این درخواست برای شما نیست!", show_alert=True); return
            
        await query.answer(); await query.edit_message_text("⚔️ **نبرد آغاز شد...**")
        p1_total, p2_total = sum([random.randint(1, 6) for _ in range(rounds)]), sum([random.randint(1, 6) for _ in range(rounds)])
        
        win_xp, lose_xp = 40, 5
        result_text = f"🏁 **نتیجه نهایی دوئل گروهی:**\n\nامتیاز بازیکن اول: {p1_total}\nامتیاز شما: {p2_total}\n\n"
        
        if p1_total > p2_total:
            update_stats(p1_id, win_xp + wager, 'win'); update_stats(p2_id, lose_xp - wager, 'loss')
            result_text += "🏆 بازیکن اول پیروز شد!"
        elif p2_total > p1_total:
            update_stats(p2_id, win_xp + wager, 'win'); update_stats(p1_id, lose_xp - wager, 'loss')
            result_text += "🏆 شما پیروز شدید!"
        else:
            update_stats(p1_id, 0, 'draw'); update_stats(p2_id, 0, 'draw')
            result_text += "🤝 مساوی شد!"
            
        await context.bot.send_message(chat_id=query.message.chat_id, text=result_text)

    if data[0] == "admin": await admin_buttons(update, context)
    if data[0] == "shop": await shop_callback(update, context)
    
    # 💥 هندلر کالبک ویترین انتخاب لقب (قابلیت ۴)
    if data[0] == "title":
        await query.answer()
        action = data[1]
        if action == "view":
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT title_name FROM user_titles WHERE telegram_id = %s", (user_id,))
            owned = [r[0] for r in cursor.fetchall()]
            cursor.close(); conn.close()
            
            kb = []
            for t in owned:
                kb.append([InlineKeyboardButton(f"✨ فعالسازی {t}", callback_data=f"title_set_{t}")])
            kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_close")])
            await query.edit_message_text("👑 **ویترین تگ‌ها و لقب‌های باز شده شما:**", reply_markup=InlineKeyboardMarkup(kb))
        elif action == "set":
            t_name = data[2]
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET title = %s WHERE telegram_id = %s", (t_name, user_id))
            conn.commit(); cursor.close(); conn.close()
            await query.edit_message_text(f"✅ لقب پروفایل شما با موفقیت به [ **{t_name}** ] تغییر یافت!")

# ==========================================
# مانیتورینگ متون و دکمه‌های شاپ
# ==========================================
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    win_rate = round((user['wins'] / user['total_games']) * 100, 1) if user['total_games'] > 0 else 0
    
    profile_text = (
        f"🎮 ━━━ **کارت عضویت کلوب نبرد** ━━━ 🎮\n\n"
        f"👤 **نام جنگجو:** {user['username']}\n🏅 **لقب ویژه:** {user['title']}\n"
        f"👑 **رتبه فعلی:** {user['rank']}\n💎 **کل امتیازات:** {user['score']} XP\n\n"
        f"🔥 **نرخ برد:** {win_rate}%\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    # 💥 اضافه شدن دکمه شیشه‌ای ویترین تگ‌ها (قابلیت ۴)
    keyboard = [[InlineKeyboardButton("👑 ویترین و انتخاب لقب", callback_data="title_view")]]
    await update.message.reply_markdown(profile_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    keyboard = [
        [InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal")],
        [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
        [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")],
        [InlineKeyboardButton("⚙️ آیتم‌های کاربردی ویژه", callback_data="shopmain_cat_utility")] # دکمه شاپ قابلیت ۲
    ]
    await update.message.reply_text(f"🏪 **به بازارچه شاپ خوش آمدید!**\n💰 موجودی: {user['score']} XP", reply_markup=InlineKeyboardMarkup(keyboard))

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = query.from_user.id; data = query.data
    await query.answer()
    
    if data.startswith("shopmain_cat_"):
        cat_type = data.replace("shopmain_cat_", "")
        if cat_type == "utility":
            # 💥 دیتای فیکس آیتم‌های کاربردی ویژه (قابلیت ۲)
            util_items = [
                {"id": "unlimited_duel", "name": "🔹 دوعل بدون محدودیت (تا ۲۰ راند)", "cost": 300},
                {"id": "high_wager", "name": "🔹 شرط‌بندی بیشتر (تا سقف ۵۰۰ کاپ)", "cost": 500},
                {"id": "lucky_dice", "name": "🔹 تاس شانس (فرصت مجدد روی تاس ۱)", "cost": 400}
            ]
            keyboard = []
            for item in util_items:
                keyboard.append([InlineKeyboardButton(f"{item['name']} | 💰 {item['cost']} XP", callback_data=f"shopbuy_util_{item['id']}_{item['cost']}")])
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shopmain_back")])
            await query.edit_message_text("⚙️ **بازارچه آیتم‌های کاربردی ربات:**", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)
        shop_items = cursor.execute("SELECT id, title_name, cost FROM shop WHERE category = %s", (cat_type,)).fetchall(); conn.close()
        keyboard = []
        for item in shop_items:
            keyboard.append([InlineKeyboardButton(f"{item['title_name']} 💰 {item['cost']} XP", callback_data=f"shopbuy_id_{item['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shopmain_back")])
        await query.edit_message_text(f"🛍️ لیست لقب‌های بخش: {CAT_NAMES[cat_type]}", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data.startswith("shopbuy_util_"):
        parts = data.split("_")
        item_id = parts[2]
        cost = int(parts[3])
        
        user = get_or_create_user(user_id, query.from_user.username)
        if user['score'] < cost:
            await query.message.reply_text("❌ امتیاز کافی برای خرید این آیتم کاربردی ندارید!"); return
            
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET score = score - %s WHERE telegram_id = %s", (cost, user_id))
        cursor.execute("""
            INSERT INTO user_items (telegram_id, item_id, quantity) VALUES (%s, %s, 1)
            ON CONFLICT (telegram_id, item_id) DO UPDATE SET quantity = user_items.quantity + 1
        """, (user_id, item_id))
        conn.commit(); conn.close()
        await query.edit_message_text("🎉 آیتم کاربردی با موفقیت خریداری و به کیف شما اضافه شد!")

    elif data.startswith("shopbuy_id_"):
        item_id = int(data.split("_")[2])
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)
        item = cursor.execute("SELECT * FROM shop WHERE id = %s", (item_id,)).fetchone()
        user = get_or_create_user(user_id, query.from_user.username)
        
        if user['score'] < item['cost']:
            await query.message.reply_text("❌ امتیاز کافی ندارید!"); conn.close(); return
            
        cursor.execute('UPDATE users SET score = score - %s, title = %s WHERE telegram_id = %s', (item['cost'], item['title_name'], user_id))
        cursor.execute("INSERT INTO user_titles (telegram_id, title_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, item['title_name']))
        conn.commit(); conn.close()
        await query.edit_message_text(f"🎉 تگ ویژه « {item['title_name']} » فعال و به ویترین لقب‌های شما اضافه شد!")

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = context.args[0].strip() if context.args else update.message.text.replace("/redeem ", "").strip()
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cdata = cursor.execute('SELECT * FROM redeem_codes WHERE code = %s', (code,)).fetchone()
    if not cdata or cdata['current_uses'] >= cdata['max_uses']:
        await update.message.reply_text("❌ کد منقضی یا نامعتبر است."); conn.close(); return
        
    cursor.execute('INSERT INTO redeem_history (telegram_id, code) VALUES (%s, %s)', (user_id, code))
    cursor.execute('UPDATE users SET title = %s WHERE telegram_id = %s', (cdata['title_name'], user_id))
    cursor.execute("INSERT INTO user_titles (telegram_id, title_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, cdata['title_name']))
    conn.commit(); conn.close()
    await update.message.reply_text(f"🎉 کد فعال شد و لقب موقت **{cdata['title_name']}** به ویترین شما اضافه شد.")

async def monitor_messages_and_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    
    if text == "🎲 پرتاب تاس": await dice_command(update, context)
    elif text == "👤 پروفایل من": await profile_command(update, context)
    elif text == "🏆 تالار افتخارات": await top_command(update, context)
    elif text == "🏪 بازارچه لقب": await shop_command(update, context)
    elif text == "ℹ️ راهنمای کلوب": await help_command(update, context)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_user_admin(update.effective_user.id): return
    keyboard = [[InlineKeyboardButton("❌ بستن پنل مدیریت", callback_data="admin_close")]]
    await update.message.reply_text("🛠 **اتاق کنترل پنل ادمین فعال است:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "admin_close":
        await query.edit_message_text("🔒 پنل مدیریت بسته شد.")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("dice", dice_command))
    application.add_handler(CommandHandler("duel", duel_command))
    application.add_handler(CommandHandler("challenge", challenge_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("top", top_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("shop", shop_command))
    application.add_handler(CommandHandler("redeem", redeem_command))
    
    application.add_handler(CallbackQueryHandler(handle_callbacks, pattern="^(pv_duel_start|pvduel_|gduel_|user_check_event|title_)"))
    application.add_handler(CallbackQueryHandler(shop_callback, pattern="^(shopmain_|shopbuy_)"))
    
    async def mid_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message and update.message.text:
            await monitor_messages_and_inputs(update, context)
            
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mid_filter))
    print("🚀 ربات با زیرساخت جدید هاردکور اینفینیتی و قابلیت‌های درخواستی روی ریل‌وی استارت شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
