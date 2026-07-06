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

def check_and_remove_expired_titles(telegram_id):
    """این تابع قبل از هر عملیات کاربر، منقضی شدن لقبش را بررسی می‌کند"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT title_expire, title FROM users WHERE telegram_id = %s", (telegram_id,))
    user = cursor.fetchone()
    
    if user and user['title_expire']:
        try:
            expire_time = datetime.strptime(user['title_expire'], "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expire_time:
                cursor.execute("UPDATE users SET title = 'بدون لقب', title_expire = NULL WHERE telegram_id = %s", (telegram_id,))
                conn.commit()
                cursor.close()
                conn.close()
                return True
        except Exception:
            pass
    cursor.close()
    conn.close()
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
    else:
        cursor.execute("UPDATE users SET username = %s, last_seen = %s WHERE telegram_id = %s", (username, now_str, telegram_id))
        conn.commit()
        
    cursor.close()
    conn.close()
    return user

def calculate_rank(score, telegram_id=None):
    """محاسبه دقیق رتبه‌بندی هاردکور با سقف ۱۴,۰۰۰ کاپ و تاپ ۱۰ پادشاهی ابدی"""
    if score < 0: return "💀 کفتار کلوب"
    elif score < 200: return "🥉 Bronze I"
    elif score < 600: return "🥉 Bronze II"
    elif score < 1200: return "🥈 Silver I"
    elif score < 2000: return "🥈 Silver II"
    elif score < 3500: return "🥇 Gold I"
    elif score < 5500: return "🥇 Gold II"
    elif score < 8000: return "🔮 Diamond"
    elif score < 10000: return "👑 Gladiator"
    elif score < 14000: return "👑 Legend"
    else:
        if telegram_id:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT telegram_id FROM users ORDER BY score DESC, telegram_id ASC LIMIT 10")
            top_10 = [row['telegram_id'] for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            if telegram_id in top_10:
                return "👑 [GOD OF DICE] Infinity"
        return "👑 Legend"

def update_stats(telegram_id, score_change, mode='win'):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT score, rank, wins, losses, draws, total_games FROM users WHERE telegram_id = %s", (telegram_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.close()
        conn.close()
        return None

    # 🛑 بررسی قانون هاردکور لیگ پادشاهان (کاپ بالای ۱۰,۰۰۰)
    if user['score'] >= 10000:
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
    cursor.execute("SELECT * FROM users ORDER BY score DESC, telegram_id ASC LIMIT %s", (limit,))
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
    new_rank = calculate_rank(new_score, telegram_id)
    
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
