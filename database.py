import sqlite3
import random
import re
from datetime import datetime, timedelta

DB_FILE = "games.db"

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
    {"name": "💎 Diamond I", "minScore": 3200},
    {"name": "💎 Diamond II", "minScore": 4200},
    {"name": "💎 Diamond III", "minScore": 5400},
    {"name": "👑 Master", "minScore": 6500},
    {"name": "🔥 Mythic Legend", "minScore": 7500},
    {"name": "🌌 Immortal Champion [Monthly Reset]", "minScore": 8500}
]

def init_db(initial_admin_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # جدول کاربران با ستون جدید draws (مساوی) و title_expire (زمان انقضای لقب)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            draws INTEGER DEFAULT 0,
            total_games INTEGER DEFAULT 0,
            score INTEGER DEFAULT 0,
            rank TEXT DEFAULT '🥉 Bronze I',
            title TEXT DEFAULT 'بدون لقب',
            title_expire TEXT,
            created_at TEXT,
            last_seen TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dice_history (
            telegram_id INTEGER,
            dice_value INTEGER,
            rolled_at TEXT
        )
    ''')
    
    # جدول فروشگاه آپدیت شده با ستون category (نوع لقب)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shop (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_name TEXT UNIQUE,
            cost INTEGER,
            category TEXT DEFAULT 'normal'
        )
    ''')
    
    # جدول ادمین‌ها
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            telegram_id INTEGER PRIMARY KEY, added_at TEXT
        )
    ''')
    
    # جدول ردیم کدها با قابلیت محدودیت تعداد استفاده و مدت زمان اعتبار لقب پس از فعال‌سازی
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY,
            title_name TEXT,
            max_uses INTEGER,
            current_uses INTEGER DEFAULT 0,
            duration_hours INTEGER
        )
    ''')
    
    # جدول ثبت استفاده کاربران از ردیم کدها (هر کس یکبار)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS redeem_history (
            telegram_id INTEGER,
            code TEXT,
            used_at TEXT,
            PRIMARY KEY (telegram_id, code)
        )
    ''')
    
    # جدول لاگ امتیازات برای ادمین (انفرادی، دوعل و غیره)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS score_logs (
            telegram_id INTEGER,
            game_type TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (telegram_id, game_type)
        )
    ''')
    
    # اعمال الترهای لازم در صورت وجود نداشتن ستون‌ها در دیتابیس قدیمی
    try: cursor.execute("ALTER TABLE users ADD COLUMN draws INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE users ADD COLUMN title_expire TEXT")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE shop ADD COLUMN category TEXT DEFAULT 'normal'")
    except sqlite3.OperationalError: pass
    
    cursor.execute('INSERT OR IGNORE INTO admins (telegram_id, added_at) VALUES (?, ?)', 
                   (initial_admin_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    
    # افزودن لقب‌های پیش‌فرض در بخش‌بندی‌های مختلف
    default_titles = [
        ("💀 تاس‌انداز مرگ", 1000, "normal"),
        ("🔮 ارباب شانس", 1500, "normal"),
        ("⚔️ گلادیاتور اعظم", 2000, "epic"),
        ("👑 امپراتور تاس", 3000, "legendary")
    ]
    for name, cost, cat in default_titles:
        cursor.execute("INSERT OR IGNORE INTO shop (title_name, cost, category) VALUES (?, ?, ?)", (name, cost, cat))
        
    conn.commit()
    conn.close()

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
    
    # بررسی انقضای لقب قبل از لود کردن پروفایل
    cursor.execute('SELECT title, title_expire FROM users WHERE telegram_id = ?', (telegram_id,))
    u_chk = cursor.fetchone()
    if u_chk and u_chk['title_expire']:
        try:
            expire_dt = datetime.strptime(u_chk['title_expire'], "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expire_dt:
                cursor.execute("UPDATE users SET title = 'بدون لقب', title_expire = NULL WHERE telegram_id = ?", (telegram_id,))
                conn.commit()
        except: pass

    user = cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)).fetchone()
    if not user:
        initial_title = 'سازنده ربات' if clean_username == "aria2773" else 'بدون لقب'
        cursor.execute('INSERT INTO users (telegram_id, username, created_at, last_seen, title) VALUES (?, ?, ?, ?, ?)', 
                       (telegram_id, clean_username, now_str, now_str, initial_title))
        conn.commit()
        user = cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)).fetchone()
    else:
        if clean_username == "aria2773" and user['title'] != 'سازنده ربات':
            cursor.execute('UPDATE users SET title = ? WHERE telegram_id = ?', ('سازنده ربات', telegram_id))
            conn.commit()
            user = cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)).fetchone()
            
        if clean_username: cursor.execute('UPDATE users SET last_seen = ?, username = ? WHERE telegram_id = ?', (now_str, clean_username, telegram_id))
        else: cursor.execute('UPDATE users SET last_seen = ? WHERE telegram_id = ?', (now_str, telegram_id))
        conn.commit()
    conn.close(); return user

def update_stats(telegram_id, score_gained, mode):
    # mode می‌تواند: 'win', 'loss', 'draw' باشد
    user = get_or_create_user(telegram_id, None)
    new_score = max(0, user['score'] + score_gained)
    new_rank = calculate_rank(new_score)
    
    win_inc = 1 if mode == 'win' else 0
    loss_inc = 1 if mode == 'loss' else 0
    draw_inc = 1 if mode == 'draw' else 0
    
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute('''
        UPDATE users SET score = ?, rank = ?, wins = wins + ?, losses = losses + ?, draws = draws + ?, total_games = total_games + 1, last_seen = ?
        WHERE telegram_id = ?
    ''', (new_score, new_rank, win_inc, loss_inc, draw_inc, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), telegram_id))
    conn.commit(); conn.close()
    return {"old_rank": user['rank'], "new_rank": new_rank, "rank_changed": new_rank != user['rank']}

def log_score_source(telegram_id, game_type):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO score_logs (telegram_id, game_type, count) VALUES (?, ?, 1)
        ON CONFLICT(telegram_id, game_type) DO UPDATE SET count = count + 1
    ''', (telegram_id, game_type))
    conn.commit(); conn.close()

def get_score_logs(telegram_id):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    logs = cursor.execute('SELECT game_type, count FROM score_logs WHERE telegram_id = ?', (telegram_id,)).fetchall()
    conn.close(); return logs

def get_titles_by_category(category):
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
    titles = cursor.execute('SELECT * FROM shop WHERE category = ?', (category,)).fetchall()
    conn.close(); return titles

def get_top_players():
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
    top_users = cursor.execute('''
        SELECT telegram_id, username, rank, title, score 
        FROM users 
        WHERE username IS NOT NULL 
        ORDER BY score DESC, total_games DESC 
        LIMIT 10
    ''').fetchall()
    conn.close(); return top_users
