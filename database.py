import sqlite3
import os
from datetime import datetime, timedelta

DB_FILE = "game_database.db"

def get_db_connection():
    """برقراری ارتباط با دیتابیس با قابلیت بازگرداندن ردیف‌ها به صورت دیکشنری"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(initial_admin_id=7430881772):
    """ساخت تمام جدول‌های مورد نیاز ربات به صورت یکپارچه"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # ۱. جدول کاربران کلوب (رفع ارور سینتکس EXISTS)
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
        created_at TEXT,
        last_seen TEXT
    )
    """)

    # ۲. جدول ادمین‌های سیستم
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        telegram_id INTEGER PRIMARY KEY
    )
    """)

    # ۳. جدول تاریخچه پرتاب تاس‌ها (برای محاسبات حمله بحرانی / Critical Hit)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dice_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        dice_value INTEGER,
        rolled_at TEXT
    )
    """)

    # ۴. جدول لاگ منابع امتیازگیری (برای مانیتورینگ ادمین)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS score_logs (
        telegram_id INTEGER,
        game_type TEXT,
        count INTEGER DEFAULT 0,
        PRIMARY KEY (telegram_id, game_type)
    )
    """)

    # ۵. جدول بازارچه لقب‌ها (Shop)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shop (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title_name TEXT UNIQUE,
        cost INTEGER,
        category TEXT
    )
    """)

    # ۶. جدول کدهای هدیه (Redeem Codes)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS redeem_codes (
        code TEXT PRIMARY KEY,
        title_name TEXT,
        max_uses INTEGER,
        current_uses INTEGER DEFAULT 0,
        duration_hours INTEGER
    )
    """)

    # ۷. جدول تاریخچه استفاده از کدهای هدیه (جلوگیری از استفاده مجدد)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS redeem_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        code TEXT,
        used_at TEXT
    )
    """)

    # ۸. جدول سیستم مدیریت رویدادها و ایونت‌های ۸ گانه
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

    # افزودن ادمین اولیه پروژه‌ در صورت عدم وجود
    cursor.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (initial_admin_id,))
    
    # پر کردن شاپ اولیه به صورت پیش‌فرض (در صورت خالی بودن جدول)
    shop_check = cursor.execute("SELECT COUNT(*) FROM shop").fetchone()[0]
    if shop_check == 0:
        default_items = [
            ('🥈 نوچه کلوب', 200, 'normal'),
            ('🥈 تاس باز', 400, 'normal'),
            ('🔮 شکارچی سایه', 1500, 'epic'),
            ('🔮 مبارز ابدی', 2500, 'epic'),
            ('👑 شاهزاده نبرد', 6000, 'legendary'),
            ('👑 گلادیاتور اعظم', 9000, 'legendary')
        ]
        cursor.executemany("INSERT INTO shop (title_name, cost, category) VALUES (?, ?, ?)", default_items)

    conn.commit()
    conn.close()

# ==========================================
# توابع کاربردی و منطقی مدیریت کاربران
# ==========================================

def is_user_admin(telegram_id):
    """بررسی سطح دسترسی ادمین"""
    conn = get_db_connection()
    admin = conn.execute("SELECT 1 FROM admins WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return admin is not None

def get_or_create_user(telegram_id, username):
    """احراز هویت یا ثبت نام کاربر جدید در دیتابیس نبرد"""
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if not user:
        # اصلاح رنک اولیه در هنگام ثبت نام به برنز ۱ بجای مقدار پیش‌فرض قدیمی
        conn.execute("""
            INSERT INTO users (telegram_id, username, score, rank, created_at, last_seen)
            VALUES (?, ?, 0, '🥉 Bronze I', ?, ?)
        """, (telegram_id, username, now_str, now_str))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    else:
        # آپدیت آخرین زمان بازدید و یوزرنیم (در صورت تغییر در تلگرام)
        conn.execute("UPDATE users SET username = ?, last_seen = ? WHERE telegram_id = ?", (username, now_str, telegram_id))
        conn.commit()
        
    conn.close()
    return user

def calculate_rank(score):
    """محاسبه دقیق رتبه‌بندی کاربران بر اساس سقف امتیازات کلوب"""
    if score < 0: return "💀 کفتار کلوب"
    elif score < 200: return "🥉 Bronze I"        # اصلاح شد: امتیاز زیر ۲۰۰ برنز ۱ هست نه گلادیاتور
    elif score < 600: return "🥉 Bronze II"
    elif score < 1200: return "🥈 Silver I"
    elif score < 2000: return "🥈 Silver II"
    elif score < 3500: return "🥇 Gold I"
    elif score < 5500: return "🥇 Gold II"
    elif score < 8000: return "🔮 Diamond"
    elif score < 12000: return "👑 Gladiator"       # اصلاح شد: انتقال جایگاه منطقی گلادیاتور به سطح بالا
    else: return "👑 Immortal Legend"

def update_stats(telegram_id, score_change, mode='win'):
    """به‌روزرسانی همزمان امتیازات، برد و باخت‌ها و لول‌آپ خودکار رنک"""
    conn = get_db_connection()
    user = conn.execute("SELECT score, rank, wins, losses, draws, total_games FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    
    if not user:
        conn.close()
        return None

    new_score = max(0, user['score'] + score_change) # جلوگیری از منفی شدن امتیاز کل زیر صفر
    new_rank = calculate_rank(new_score)
    
    # اصلاح باگ منطقی: مقایسه رنک جدید با رنک قبلی (نه با امتیاز قبلی)
    rank_changed = (new_rank != user['rank']) 
    
    w, l, d = user['wins'], user['losses'], user['draws']
    if mode == 'win': w += 1
    elif mode == 'loss': l += 1
    elif mode == 'draw': d += 1
    
    total = w + l + d
    
    conn.execute("""
        UPDATE users 
        SET score = ?, rank = ?, wins = ?, losses = ?, draws = ?, total_games = ?
        WHERE telegram_id = ?
    """, (new_score, new_rank, w, l, d, total, telegram_id))
    
    conn.commit()
    conn.close()
    
    return {"new_score": new_score, "new_rank": new_rank, "rank_changed": rank_changed}

def get_top_players(limit=10):
    """دریافت لیست مشاهیر و ۱۰ گلادیاتور برتر کلوب"""
    conn = get_db_connection()
    players = conn.execute("SELECT * FROM users ORDER BY score DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return players 

# ==========================================
# توابع جدید و حیاتی افزوده شده برای سیستم لقب‌ها (بدون حذف توابع قبلی)
# ==========================================

def buy_title(telegram_id, title_name):
    """خرید لقب از بازارچه و کسر امتیاز کاربر"""
    conn = get_db_connection()
    user = conn.execute("SELECT score FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    item = conn.execute("SELECT cost FROM shop WHERE title_name = ?", (title_name,)).fetchone()
    
    if not user or not item:
        conn.close()
        return {"status": "error", "message": "کاربر یا آیتم یافت نشد."}
        
    if user['score'] < item['cost']:
        conn.close()
        return {"status": "low_score", "message": "امتیاز شما کافی نیست."}
        
    new_score = user['score'] - item['cost']
    new_rank = calculate_rank(new_score)
    
    conn.execute("""
        UPDATE users 
        SET score = ?, rank = ?, title = ?, title_expire = NULL 
        WHERE telegram_id = ?
    """, (new_score, new_rank, title_name, telegram_id))
    
    conn.commit()
    conn.close()
    return {"status": "success", "new_score": new_score, "title": title_name}

def set_user_title_admin(telegram_id, title_name):
    """تنظیم دستی لقب کاربر توسط ادمین"""
    conn = get_db_connection()
    conn.execute("UPDATE users SET title = ?, title_expire = NULL WHERE telegram_id = ?", (title_name, telegram_id))
    conn.commit()
    conn.close()
    return True

def get_shop_items():
    """دریافت لیست تمام آیتم‌های موجود در شاپ"""
    conn = get_db_connection()
    items = conn.execute("SELECT * FROM shop").fetchall()
    conn.close()
    return items
