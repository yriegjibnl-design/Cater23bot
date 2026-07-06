import os
import sqlite3
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime

# 🔗 اتصال خودکار به دیتابیس PostgreSQL ریل‌وی از طریق متغیر محیطی
DATABASE_URL = os.getenv("DATABASE_URL")
OLD_DB_FILE = "game_database.db"

def get_db_connection():
    """برقراری ارتباط با دیتابیس PostgreSQL ریل‌وی"""
    return psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)

def init_db(initial_admin_id=7430881772):
    """ساخت تمام جدول‌های مورد نیاز ربات در PostgreSQL و انتقال دیتای قدیمی"""
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
        print("✅ جدول‌های PostgreSQL با موفقیت ست‌آپ شدند!")
        
        # 🔄 انتقال اتوماتیک کل دیتای لوکل قدیمی به سرور جدید ریل‌وی
        migrate_old_sqlite_data(cursor, conn)

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ خطا در ساخت جدول‌های پستگرس: {e}")

def migrate_old_sqlite_data(pg_cursor, pg_conn):
    """انتقال ۱۰۰٪ امن دیتای قدیمی کاربران از فایل SQLite به PostgreSQL ریل‌وی"""
    if os.path.exists(OLD_DB_FILE):
        print("📦 دیتابیس قدیمی SQLite پیدا شد! آغاز عملیات انتقال دیتای کاربران...")
        try:
            lite_conn = sqlite3.connect(OLD_DB_FILE)
            lite_cursor = lite_conn.cursor()
            
            # انتقال جدول کاربران
            lite_cursor.execute("SELECT telegram_id, username, score, rank, title, title_expire, wins, losses, draws, total_games, created_at, last_seen FROM users")
            for user in lite_cursor.fetchall():
                pg_cursor.execute("""
                INSERT INTO users (telegram_id, username, score, rank, title, title_expire, wins, losses, draws, total_games, created_at, last_seen)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (telegram_id) DO NOTHING;
                """, user)
                
            # انتقال جدول ادمین‌ها
            lite_cursor.execute("SELECT telegram_id FROM admins")
            for admin in lite_cursor.fetchall():
                pg_cursor.execute("INSERT INTO admins (telegram_id) VALUES (%s) ON CONFLICT (telegram_id) DO NOTHING;", admin)

            # انتقال کدهای هدیه (در صورت نیاز)
            lite_cursor.execute("SELECT code, title_name, max_uses, current_uses, duration_hours FROM redeem_codes")
            for code in lite_cursor.fetchall():
                pg_cursor.execute("INSERT INTO redeem_codes (code, title_name, max_uses, current_uses, duration_hours) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (code) DO NOTHING;", code)

            pg_conn.commit()
            lite_cursor.close()
            lite_conn.close()
            
            # تغییر نام فایل قدیمی جهت جلوگیری از اجرای مجدد عملیات انتقال
            os.rename(OLD_DB_FILE, f"migrated_{OLD_DB_FILE}")
            print("🚀 انتقال اطلاعات تمام کاربران با موفقیت ۱۰۰٪ به پایان رسید و فایل لوکال آرشیو شد!")
        except Exception as e:
            print(f"⚠️ خطایی حین مهاجرت دیتا رخ داد: {e}")

# ==========================================
# سیستم بک‌گراند جابِ چک کردن انقضای لقب‌ها راس ثانیه (Lazy Method کاملاً بهینه)
# ==========================================
def check_and_remove_expired_titles(telegram_id):
    """این تابع قبل از هر عملیات کاربر، منقضی شدن لقبش را بررسی می‌کند"""
    conn = get_db_connection()
    user = conn.execute("SELECT title_expire, title FROM users WHERE telegram_id = %s", (telegram_id,)).fetchone()
    
    if user and user['title_expire']:
        try:
            expire_time = datetime.strptime(user['title_expire'], "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expire_time:
                # مهلت لقب تمام شده است!
                conn.execute("UPDATE users SET title = 'بدون لقب', title_expire = NULL WHERE telegram_id = %s", (telegram_id,))
                conn.commit()
                conn.close()
                return True # لقب منقضی شد
        except Exception:
            pass
    conn.close()
    return False

# ==========================================
# توابع کاربردی و منطقی مدیریت کاربران (نسخه PostgreSQL)
# ==========================================

def is_user_admin(telegram_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM admins WHERE telegram_id = %s", (telegram_id,))
    admin = cursor.fetchone()
    cursor.close()
    conn.close()
    return admin is not None

def get_or_create_user(telegram_id, username):
    check_and_remove_expired_titles(telegram_id) # چک کردن لقب قبل از خواندن اطلاعات اکانت
    
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
    else:
        cursor.execute("UPDATE users SET username = %s, last_seen = %s WHERE telegram_id = %s", (username, now_str, telegram_id))
        conn.commit()
        
    cursor.close()
    conn.close()
    return user

def calculate_rank(score):
    if score < 0: return "💀 کفتار کلوب"
    elif score < 200: return "🥉 Bronze I"
    elif score < 600: return "🥉 Bronze II"
    elif score < 1200: return "🥈 Silver I"
    elif score < 2000: return "🥈 Silver II"
    elif score < 3500: return "🥇 Gold I"
    elif score < 5500: return "🥇 Gold II"
    elif score < 8000: return "🔮 Diamond"
    elif score < 12000: return "👑 Gladiator"
    else: return "👑 Immortal Legend"

def update_stats(telegram_id, score_change, mode='win'):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT score, rank, wins, losses, draws, total_games FROM users WHERE telegram_id = %s", (telegram_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.close()
        conn.close()
        return None

    new_score = max(0, user['score'] + score_change)
    new_rank = calculate_rank(new_score)
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

def buy_title(telegram_id, title_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT score FROM users WHERE telegram_id = %s", (telegram_id,))
    user = cursor.fetchone()
    cursor.execute("SELECT cost FROM shop WHERE title_name = %s", (title_name,))
    item = cursor.fetchone()
    
    if not user or not item:
        cursor.close()
        conn.close()
        return {"status": "error", "message": "کاربر یا آیتم یافت نشد."}
        
    if user['score'] < item['cost']:
        cursor.close()
        conn.close()
        return {"status": "low_score", "message": "امتیاز شما کافی نیست."}
        
    new_score = user['score'] - item['cost']
    new_rank = calculate_rank(new_score)
    
    cursor.execute("""
        UPDATE users 
        SET score = %s, rank = %s, title = %s, title_expire = NULL 
        WHERE telegram_id = %s
    """, (new_score, new_rank, title_name, telegram_id))
    
    conn.commit()
    cursor.close()
    conn.close()
    return {"status": "success", "new_score": new_score, "title": title_name}

def set_user_title_admin(telegram_id, title_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET title = %s, title_expire = NULL WHERE telegram_id = %s", (title_name, telegram_id))
    conn.commit()
    cursor.close()
    conn.close()
    return True

def get_shop_items():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shop")
    items = cursor.fetchall()
    cursor.close()
    conn.close()
    return items
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
