import sqlite3
import random
import re
from datetime import datetime

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

def init_db():
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dice_history (
            telegram_id INTEGER, dice_value INTEGER, rolled_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shop (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title_name TEXT UNIQUE, cost INTEGER
        )
    ''')
    try: cursor.execute("ALTER TABLE users ADD COLUMN last_seen TEXT")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE users ADD COLUMN title TEXT DEFAULT 'بدون لقب'")
    except sqlite3.OperationalError: pass
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (telegram_id INTEGER PRIMARY KEY, added_at TEXT)
    ''')
    conn.commit()
    conn.close()

def calculate_rank(score):
    current_rank = RANKS[0]["name"]
    for rank in RANKS:
        if score >= rank["minScore"]: current_rank = rank["name"]
        else: break
    return current_rank

def is_user_admin(telegram_id, initial_admin_id):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO admins (telegram_id, added_at) VALUES (?, ?)', 
                   (initial_admin_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    res = cursor.execute('SELECT 1 FROM admins WHERE telegram_id = ?', (telegram_id,)).fetchone()
    conn.commit(); conn.close()
    return res is not None

def get_or_create_user(telegram_id, username):
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_username = username.replace("@", "") if username else None
    
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
    top_users = cursor.execute('''
        SELECT telegram_id, username, rank, title, score FROM users 
        WHERE username IS NOT NULL ORDER BY score DESC, total_games DESC LIMIT 10
    ''').fetchall()
    conn.close(); return top_users

def sync_from_text(text):
    lines = text.split("\n")
    current_username = None
    updated_count = 0
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    for line in lines:
        user_match = re.search(r'(?:\d+\.\s*|👑|⚡|🛡️|🎖️)\s*([A-Za-z0-9_]+)', line)
        if user_match: current_username = user_match.group(1).strip()
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
            updated_count += 1; current_username = None
    conn.commit(); conn.close(); return updated_count
