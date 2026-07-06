import os
import sys
import sqlite3
import logging
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union, Tuple

# ==============================================================================
# DATABASE CONFIGURATION & ENVIRONMENT SETUP
# ==============================================================================

# Setup logging system with detailed descriptive formatting
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("DatabaseManager")

# Retrieve production database URL from environment variable if present
DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
DB_FILE: str = "game_database.db"
OLD_DB_FILE: str = "game_database.db"

# Identify database engine mode
if DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")):
    IS_POSTGRES = True
    logger.info("Database Mode: Production PostgreSQL detected via environment variable.")
else:
    IS_POSTGRES = False
    logger.info(f"Database Mode: Local SQLite fallback detected. File pathway: {DB_FILE}")

# ==============================================================================
# CROSS-DATABASE COMPATIBILITY ADAPTERS
# ==============================================================================

def adapt_query(query_string: str) -> str:
    """
    Translates standard placeholder tokens to ensure 100% interoperability 
    between SQLite engine tokens and PostgreSQL engine tokens.
    """
    if IS_POSTGRES:
        return query_string.replace("?", "%s")
    return query_string

def get_db_connection():
    """
    Establishes and returns a structured database connection object matching 
    the active infrastructure context (PostgreSQL or SQLite).
    """
    try:
        if IS_POSTGRES:
            connection = psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)
            connection.autocommit = False
            return connection
        else:
            connection = sqlite3.connect(DB_FILE)
            connection.row_factory = sqlite3.Row
            return connection
    except Exception as error:
        logger.critical(f"Fatal error initializing database connection instance: {error}")
        raise error

# Alias implementation to fulfill system import compatibility
get_connection = get_db_connection

# ==============================================================================
# DATABASE SCHEMA INITIALIZATION & MIGRATION ORCHESTRATION
# ==============================================================================

def init_db(initial_admin_id: int = 7430881772) -> None:
    """
    Creates all necessary application tables with appropriate constraints, 
    indexes, and default rows. Automatically manages engine-specific types.
    """
    logger.info("Beginning database architectural setup and schema verification...")
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        if IS_POSTGRES:
            logger.info("Executing PostgreSQL structural configuration sequence...")
            
            # 1. Users Table
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

            # 2. Admins Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    telegram_id BIGINT PRIMARY KEY
                );
            """)

            # 3. Dice History Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dice_history (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT,
                    dice_value INT,
                    rolled_at VARCHAR(50)
                );
            """)

            # 4. Score Logs Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS score_logs (
                    telegram_id BIGINT,
                    game_type VARCHAR(100),
                    count INT DEFAULT 0,
                    PRIMARY KEY (telegram_id, game_type)
                );
            """)

            # 5. Shop Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shop (
                    id SERIAL PRIMARY KEY,
                    title_name VARCHAR(255) UNIQUE,
                    cost INT,
                    category VARCHAR(50)
                );
            """)

            # 6. Redeem Codes Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS redeem_codes (
                    code VARCHAR(255) PRIMARY KEY,
                    title_name VARCHAR(255),
                    max_uses INT,
                    current_uses INT DEFAULT 0,
                    duration_hours INT
                );
            """)

            # 7. Redeem History Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS redeem_history (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT,
                    code VARCHAR(255),
                    used_at VARCHAR(50)
                );
            """)

            # 8. Active Event Table
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

            # 9. Duel Links Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS duel_links (
                    id SERIAL PRIMARY KEY,
                    player_id BIGINT,
                    opponent_id BIGINT,
                    status VARCHAR(50),
                    created_at VARCHAR(50)
                );
            """)

            # 10. User Items Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_items (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT,
                    item_name VARCHAR(255),
                    purchased_at VARCHAR(50)
                );
            """)

            # 11. User Titles Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_titles (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT,
                    title_name VARCHAR(255),
                    unlocked_at VARCHAR(50)
                );
            """)

            # 12. Infinity Rank Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS infinity_rank (
                    telegram_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    score INT,
                    updated_at VARCHAR(50)
                );
            """)

        else:
            logger.info("Executing SQLite structural configuration sequence...")
            
            # 1. Users Table (SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    score INTEGER DEFAULT 0,
                    rank TEXT DEFAULT '🥉 Bronze I',
                    title TEXT DEFAULT 'بدون لقب',
                    title_expire TEXT DEFAULT NULL,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    draws INTEGER DEFAULT 0,
                    total_games INTEGER DEFAULT 0,
                    created_at TEXT,
                    last_seen TEXT
                );
            """)

            # 2. Admins Table (SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    telegram_id INTEGER PRIMARY KEY
                );
            """)

            # 3. Dice History Table (SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dice_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    dice_value INTEGER,
                    rolled_at TEXT
                );
            """)

            # 4. Score Logs Table (SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS score_logs (
                    telegram_id INTEGER,
                    game_type TEXT,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (telegram_id, game_type)
                );
            """)

            # 5. Shop Table (SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shop (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title_name TEXT UNIQUE,
                    cost INTEGER,
                    category TEXT
                );
            """)

            # 6. Redeem Codes Table (SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS redeem_codes (
                    code TEXT PRIMARY KEY,
                    title_name TEXT,
                    max_uses INTEGER,
                    current_uses INTEGER DEFAULT 0,
                    duration_hours INTEGER
                );
            """)

            # 7. Redeem History Table (SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS redeem_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    code TEXT,
                    used_at TEXT
                );
            """)

            # 8. Active Event Table (SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_event (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER,
                    event_name TEXT,
                    end_time TEXT,
                    extra_data TEXT,
                    reward_type TEXT,
                    reward_value TEXT
                );
            """)

            # 9. Duel Links Table (SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS duel_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER,
                    opponent_id INTEGER,
                    status TEXT,
                    created_at TEXT
                );
            """)

            # 10. User Items Table (SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    item_name TEXT,
                    purchased_at TEXT
                );
            """)

            # 11. User Titles Table (SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_titles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    title_name TEXT,
                    unlocked_at TEXT
                );
            """)

            # 12. Infinity Rank Table (SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS infinity_rank (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    score INTEGER,
                    updated_at TEXT
                );
            """)

        # Optimization Indexes for High Performance Read/Write Operations
        cursor.execute(adapt_query("CREATE INDEX IF NOT EXISTS idx_users_score ON users(score DESC);"))
        cursor.execute(adapt_query("CREATE INDEX IF NOT EXISTS idx_dice_history_uid ON dice_history(telegram_id);"))
        cursor.execute(adapt_query("CREATE INDEX IF NOT EXISTS idx_user_items_uid ON user_items(telegram_id);"))
        cursor.execute(adapt_query("CREATE INDEX IF NOT EXISTS idx_user_titles_uid ON user_titles(telegram_id);"))

        # Seed system administrators
        admin_query = "INSERT INTO admins (telegram_id) VALUES (?) ON CONFLICT (telegram_id) DO NOTHING;"
        cursor.execute(adapt_query(admin_query), (initial_admin_id,))

        # Seed catalog marketplace catalog data safely
        check_shop_query = "SELECT COUNT(*) FROM shop;"
        cursor.execute(adapt_query(check_shop_query))
        shop_count = cursor.fetchone()[0]

        if shop_count == 0:
            logger.info("Populating database with standard shop title inventory packages...")
            default_items = [
                ('🥈 نوچه کلوب', 200, 'normal'),
                ('🥈 تاس باز', 400, 'normal'),
                ('🔮 شکارچی سایه', 1500, 'epic'),
                ('🔮 مبارز ابدی', 2500, 'epic'),
                ('👑 شاهزاده نبرد', 6000, 'legendary'),
                ('👑 گلادیاتور اعظم', 9000, 'legendary')
            ]
            insert_shop_query = "INSERT INTO shop (title_name, cost, category) VALUES (?, ?, ?) ON CONFLICT (title_name) DO NOTHING;"
            for item in default_items:
                cursor.execute(adapt_query(insert_shop_query), item)

        connection.commit()
        logger.info("Database engine components verified and securely established.")

        # Execute automated server-side production onboarding migrations if needed
        if IS_POSTGRES:
            migrate_old_sqlite_data(cursor, connection)

    except Exception as error:
        connection.rollback()
        logger.error(f"Critical error occurred during architectural initialization: {error}")
    finally:
        cursor.close()
        connection.close()

def migrate_old_sqlite_data(pg_cursor, pg_conn) -> None:
    """
    Executes deep isolated row parsing from local archived SQLite databases 
    and migrates them gracefully into remote deployment engines.
    """
    # Verify presence of migration target file pathway securely
    if os.path.exists(OLD_DB_FILE) and os.path.getsize(OLD_DB_FILE) > 0:
        # Prevent circular logic loop processing if the local database file matches active setup
        if not IS_POSTGRES:
            return

        logger.info(f"Discovered historical SQLite record archive container: '{OLD_DB_FILE}'. Starting onboarding migration sequence...")
        try:
            lite_conn = sqlite3.connect(OLD_DB_FILE)
            lite_cursor = lite_conn.cursor()

            # 1. Migrate Users records
            lite_cursor.execute("SELECT telegram_id, username, score, rank, title, title_expire, wins, losses, draws, total_games, created_at, last_seen FROM users")
            user_rows = lite_cursor.fetchall()
            logger.info(f"Migrating {len(user_rows)} user profiles cleanly into production systems...")
            user_insert = """
                INSERT INTO users (telegram_id, username, score, rank, title, title_expire, wins, losses, draws, total_games, created_at, last_seen)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (telegram_id) DO NOTHING;
            """
            for row in user_rows:
                pg_cursor.execute(user_insert, row)

            # 2. Migrate System Administrators records
            lite_cursor.execute("SELECT telegram_id FROM admins")
            admin_rows = lite_cursor.fetchall()
            for row in admin_rows:
                pg_cursor.execute("INSERT INTO admins (telegram_id) VALUES (%s) ON CONFLICT (telegram_id) DO NOTHING;", row)

            # 3. Migrate Redeem Codes configuration catalog matrices
            lite_cursor.execute("SELECT code, title_name, max_uses, current_uses, duration_hours FROM redeem_codes")
            code_rows = lite_cursor.fetchall()
            code_insert = """
                INSERT INTO redeem_codes (code, title_name, max_uses, current_uses, duration_hours)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT (code) DO NOTHING;
            """
            for row in code_rows:
                pg_cursor.execute(code_insert, row)

            pg_conn.commit()
            lite_cursor.close()
            lite_conn.close()

            # Safely archive the source binary container asset file pathing structures
            archive_target = f"migrated_archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{OLD_DB_FILE}"
            os.rename(OLD_DB_FILE, archive_target)
            logger.info(f"Data layer asset translation complete. Local file securely renamed to: '{archive_target}'")

        except Exception as error:
            pg_conn.rollback()
            logger.error(f"Encountered unexpected transaction abort exception during structural translation: {error}")

# ==============================================================================
# AUTOMATED LAZY TITLE EXPIRATION CHECKER
# ==============================================================================

def check_and_remove_expired_titles(telegram_id: int) -> bool:
    """
    Performs critical structural evaluation comparing the expiration time 
    metrics of user ranks against standard system server time runtime calculations.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    status_changed = False

    try:
        select_query = "SELECT title_expire, title FROM users WHERE telegram_id = ?;"
        cursor.execute(adapt_query(select_query), (telegram_id,))
        record = cursor.fetchone()

        if record and record['title_expire']:
            try:
                expiration_threshold = datetime.strptime(record['title_expire'], "%Y-%m-%d %H:%M:%S")
                if datetime.now() > expiration_threshold:
                    logger.info(f"Target profile token sequence {telegram_id} matches expiration criteria for tag: '{record['title']}'")
                    update_query = "UPDATE users SET title = 'بدون لقب', title_expire = NULL WHERE telegram_id = ?;"
                    cursor.execute(adapt_query(update_query), (telegram_id,))
                    connection.commit()
                    status_changed = True
            except ValueError:
                logger.error(f"Malformed textual timestamps parsed on account validation processing routine for UID: {telegram_id}")
    except Exception as error:
        connection.rollback()
        logger.error(f"Error handling lazy title verification routines: {error}")
    finally:
        cursor.close()
        connection.close()
    
    return status_changed

# ==============================================================================
# CORE USER MANAGEMENT SYSTEM FUNCTIONS
# ==============================================================================

def is_user_admin(telegram_id: int) -> bool:
    """
    Validates identity authorization parameters inside the access control layer.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    is_admin = False

    try:
        admin_query = "SELECT 1 FROM admins WHERE telegram_id = ?;"
        cursor.execute(adapt_query(admin_query), (telegram_id,))
        record = cursor.fetchone()
        if record is not None:
            is_admin = True
    except Exception as error:
        logger.error(f"Error executing security structural validation lookup: {error}")
    finally:
        cursor.close()
        connection.close()

    return is_admin

def get_or_create_user(telegram_id: int, username: Optional[str]) -> Any:
    """
    Retrieves or signs up user profiles smoothly inside centralized systems.
    """
    # Execute structural pre-flight lazy calculations
    check_and_remove_expired_titles(telegram_id)

    connection = get_db_connection()
    cursor = connection.cursor()
    current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sanitized_username = username if username else f"User_{telegram_id}"

    try:
        select_query = "SELECT * FROM users WHERE telegram_id = ?;"
        cursor.execute(adapt_query(select_query), (telegram_id,))
        user_record = cursor.fetchone()

        if not user_record:
            logger.info(f"Registering new user profile sequence under reference token: {telegram_id}")
            insert_query = """
                INSERT INTO users (telegram_id, username, score, rank, created_at, last_seen)
                VALUES (?, ?, 0, '🥉 Bronze I', ?, ?);
            """
            cursor.execute(adapt_query(insert_query), (telegram_id, sanitized_username, current_timestamp, current_timestamp))
            connection.commit()

            cursor.execute(adapt_query(select_query), (telegram_id,))
            user_record = cursor.fetchone()
        else:
            update_query = "UPDATE users SET username = ?, last_seen = ? WHERE telegram_id = ?;"
            cursor.execute(adapt_query(update_query), (sanitized_username, current_timestamp, telegram_id))
            connection.commit()

            cursor.execute(adapt_query(select_query), (telegram_id,))
            user_record = cursor.fetchone()

    except Exception as error:
        connection.rollback()
        logger.error(f"Error occurred during registration/synchronization phase: {error}")
        user_record = None
    finally:
        cursor.close()
        connection.close()

    return user_record

def calculate_rank(score: int) -> str:
    """
    Calculates numerical character tier progressions algorithmically.
    """
    if score < 0:
        return "💀 کفتار کلوب"
    elif score < 200:
        return "🥉 Bronze I"
    elif score < 600:
        return "🥉 Bronze II"
    elif score < 1200:
        return "🥈 Silver I"
    elif score < 2000:
        return "🥈 Silver II"
    elif score < 3500:
        return "🥇 Gold I"
    elif score < 5500:
        return "🥇 Gold II"
    elif score < 8000:
        return "🔮 Diamond"
    elif score < 12000:
        return "👑 Gladiator"
    else:
        return "👑 Immortal Legend"

def update_stats(telegram_id: int, score_change: int, mode: str = 'win') -> Optional[Dict[str, Any]]:
    """
    Updates player records, handles tier shifts, and tracks win/loss tallies.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    output_payload = None

    try:
        select_query = "SELECT score, rank, wins, losses, draws, total_games FROM users WHERE telegram_id = ?;"
        cursor.execute(adapt_query(select_query), (telegram_id,))
        user = cursor.fetchone()

        if user:
            current_score = user['score']
            old_rank = user['rank']
            wins = user['wins']
            losses = user['losses']
            draws = user['draws']

            new_score = max(0, current_score + score_change)
            new_rank = calculate_rank(new_score)
            rank_changed = (new_rank != old_rank)

            if mode == 'win':
                wins += 1
            elif mode == 'loss':
                losses += 1
            elif mode == 'draw':
                draws += 1

            total_games = wins + losses + draws

            update_query = """
                UPDATE users 
                SET score = ?, rank = ?, wins = ?, losses = ?, draws = ?, total_games = ? 
                WHERE telegram_id = ?;
            """
            cursor.execute(adapt_query(update_query), (new_score, new_rank, wins, losses, draws, total_games, telegram_id))
            connection.commit()

            output_payload = {
                "new_score": new_score,
                "new_rank": new_rank,
                "rank_changed": rank_changed
            }
            
            # Keep global leaderboard synced
            update_infinity_ranks(cursor, connection)
            
    except Exception as error:
        connection.rollback()
        logger.error(f"Error executing score balancing metrics updates: {error}")
    finally:
        cursor.close()
        connection.close()

    return output_payload

def get_top_players(limit: int = 10) -> List[Any]:
    """
    Fetches the highest scoring players from the primary data repository.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    leaderboard_dataset = []

    try:
        leaderboard_query = "SELECT * FROM users ORDER BY score DESC LIMIT ?;"
        cursor.execute(adapt_query(leaderboard_query), (limit,))
        leaderboard_dataset = cursor.fetchall()
    except Exception as error:
        logger.error(f"Failed to query global high scores data matrix: {error}")
    finally:
        cursor.close()
        connection.close()

    return leaderboard_dataset

# ==============================================================================
# SHOP & TITLE ASSET INVENTORY MANAGEMENT
# ==============================================================================

def buy_title(telegram_id: int, title_name: str) -> Dict[str, Any]:
    """
    Deducts balance points to grant user profile cosmetic upgrades.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    execution_result = {"status": "error", "message": "An unexpected server-side query error occurred."}

    try:
        user_query = "SELECT score FROM users WHERE telegram_id = ?;"
        cursor.execute(adapt_query(user_query), (telegram_id,))
        user_record = cursor.fetchone()

        item_query = "SELECT cost FROM shop WHERE title_name = ?;"
        cursor.execute(adapt_query(item_query), (title_name,))
        item_record = cursor.fetchone()

        if not user_record or not item_record:
            execution_result = {"status": "error", "message": "The specified user profile or marketplace item was not found."}
        elif user_record['score'] < item_record['cost']:
            execution_result = {"status": "low_score", "message": "Your score balance is insufficient to finalize this transaction."}
        else:
            remaining_balance = user_record['score'] - item_record['cost']
            revised_rank = calculate_rank(remaining_balance)

            # Update the user's current equipped title
            update_user_query = """
                UPDATE users SET score = ?, rank = ?, title = ?, title_expire = NULL 
                WHERE telegram_id = ?;
            """
            cursor.execute(adapt_query(update_user_query), (remaining_balance, revised_rank, title_name, telegram_id))

            # Store purchase history
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            item_log_query = "INSERT INTO user_items (telegram_id, item_name, purchased_at) VALUES (?, ?, ?);"
            cursor.execute(adapt_query(item_log_query), (telegram_id, title_name, timestamp))

            # Unlock title permanently in inventory matrix
            title_log_query = "INSERT INTO user_titles (telegram_id, title_name, unlocked_at) VALUES (?, ?, ?);"
            cursor.execute(adapt_query(title_log_query), (telegram_id, title_name, timestamp))

            connection.commit()
            execution_result = {
                "status": "success",
                "new_score": remaining_balance,
                "title": title_name
            }
            
            update_infinity_ranks(cursor, connection)

    except Exception as error:
        connection.rollback()
        logger.error(f"Transaction abort registered inside buy_title workflow matrix: {error}")
    finally:
        cursor.close()
        connection.close()

    return execution_result

def set_user_title_admin(telegram_id: int, title_name: str, expiration_hours: Optional[int] = None) -> bool:
    """
    Sets or updates custom user titles via administrator configuration panels.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    operation_success = False

    try:
        expire_str = None
        if expiration_hours and expiration_hours > 0:
            expire_str = (datetime.now() + timedelta(hours=expiration_hours)).strftime("%Y-%m-%d %H:%M:%S")

        update_query = "UPDATE users SET title = ?, title_expire = ? WHERE telegram_id = ?;"
        cursor.execute(adapt_query(update_query), (title_name, expire_str, telegram_id))
        
        # Save title inside permanent unlocking vault
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        vault_query = "INSERT INTO user_titles (telegram_id, title_name, unlocked_at) VALUES (?, ?, ?);"
        cursor.execute(adapt_query(vault_query), (telegram_id, title_name, now_str))

        connection.commit()
        operation_success = True
    except Exception as error:
        connection.rollback()
        logger.error(f"Failed administrative title adjustment transaction sequence: {error}")
    finally:
        cursor.close()
        connection.close()

    return operation_success

def get_shop_items() -> List[Any]:
    """
    Returns the complete list of available items listed in the store database.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    catalog_items = []

    try:
        shop_query = "SELECT * FROM shop ORDER BY cost ASC;"
        cursor.execute(adapt_query(shop_query))
        catalog_items = cursor.fetchall()
    except Exception as error:
        logger.error(f"Failed to fetch shop inventory entries: {error}")
    finally:
        cursor.close()
        connection.close()

    return catalog_items

def add_shop_item(title_name: str, cost: int, category: str = 'normal') -> bool:
    """
    Adds a new item to the store catalog.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    success = False
    try:
        query = "INSERT INTO shop (title_name, cost, category) VALUES (?, ?, ?) ON CONFLICT (title_name) DO UPDATE SET cost = EXCLUDED.cost, category = EXCLUDED.category;"
        cursor.execute(adapt_query(query), (title_name, cost, category))
        connection.commit()
        success = True
    except Exception as error:
        connection.rollback()
        logger.error(f"Failed to insert or update shop item layout: {error}")
    finally:
        cursor.close()
        connection.close()
    return success

# ==============================================================================
# PROMOTIONAL VOUCHERS & REDEEM CODES SUB-SYSTEM
# ==============================================================================

def add_redeem_code(code: str, title_name: str, max_uses: int, duration_hours: int) -> bool:
    """
    Creates a gift code with maximum usage constraints and duration limits.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    success = False

    try:
        query = """
            INSERT INTO redeem_codes (code, title_name, max_uses, current_uses, duration_hours)
            VALUES (?, ?, ?, 0, ?) ON CONFLICT (code) DO UPDATE 
            SET title_name = EXCLUDED.title_name, max_uses = EXCLUDED.max_uses, duration_hours = EXCLUDED.duration_hours;
        """
        cursor.execute(adapt_query(query), (code, title_name, max_uses, duration_hours))
        connection.commit()
        success = True
    except Exception as error:
        connection.rollback()
        logger.error(f"Failed to create promo voucher entity structure: {error}")
    finally:
        cursor.close()
        connection.close()

    return success

def use_redeem_code(telegram_id: int, code: str) -> Dict[str, Any]:
    """
    Processes promo codes, checks usage logs, and claims cosmetic updates.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    response = {"status": "error", "message": "Process aborted due to database verification breakdown."}
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Check if code exists
        cursor.execute(adapt_query("SELECT * FROM redeem_codes WHERE code = ?;"), (code,))
        voucher = cursor.fetchone()

        if not voucher:
            return {"status": "not_found", "message": "The promotional code provided is invalid or has expired."}

        # Check if the user has already used this code
        cursor.execute(adapt_query("SELECT 1 FROM redeem_history WHERE telegram_id = ? AND code = ?;"), (telegram_id, code))
        already_used = cursor.fetchone()

        if already_used:
            return {"status": "already_used", "message": "You have already claimed this promotional code reward pack."}

        if voucher['current_uses'] >= voucher['max_uses']:
            return {"status": "depleted", "message": "This promotional coupon code usage allocation limit has been reached."}

        # Complete redemption transaction safely
        new_uses = voucher['current_uses'] + 1
        cursor.execute(adapt_query("UPDATE redeem_codes SET current_uses = ? WHERE code = ?;"), (new_uses, code))

        # Log usage history
        cursor.execute(adapt_query("INSERT INTO redeem_history (telegram_id, code, used_at) VALUES (?, ?, ?);"), (telegram_id, code, now_str))

        # Apply promotional title with optional expiration timeline configuration
        duration = int(voucher['duration_hours'])
        expire_date_str = None
        if duration > 0:
            expire_date_str = (datetime.now() + timedelta(hours=duration)).strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(adapt_query("UPDATE users SET title = ?, title_expire = ? WHERE telegram_id = ?;"), (voucher['title_name'], expire_date_str, telegram_id))
        
        # Save historical asset entry mapping parameters
        cursor.execute(adapt_query("INSERT INTO user_titles (telegram_id, title_name, unlocked_at) VALUES (?, ?, ?);"), (telegram_id, voucher['title_name'], now_str))

        connection.commit()
        response = {
            "status": "success",
            "message": f"Successfully activated! You received the title: {voucher['title_name']}",
            "title_name": voucher['title_name']
        }

    except Exception as error:
        connection.rollback()
        logger.error(f"Critical execution error context within voucher processing stream: {error}")
    finally:
        cursor.close()
        connection.close()

    return response

# ==============================================================================
# AUDIT LOGGING & GAME ACTIVITY STATISTICS SYSTEMS
# ==============================================================================

def log_dice_roll(telegram_id: int, dice_value: int) -> None:
    """
    Saves mini-game dice rolling results to the telemetry logs database.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        query = "INSERT INTO dice_history (telegram_id, dice_value, rolled_at) VALUES (?, ?, ?);"
        cursor.execute(adapt_query(query), (telegram_id, dice_value, now_str))
        connection.commit()
    except Exception as error:
        connection.rollback()
        logger.error(f"Failed telemetry logging insertion loop inside dice tracking tables: {error}")
    finally:
        cursor.close()
        connection.close()

def log_score_change(telegram_id: int, game_type: str, count_increment: int = 1) -> None:
    """
    Updates total match completions for accurate achievement tracking.
    """
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        select_query = "SELECT count FROM score_logs WHERE telegram_id = ? AND game_type = ?;"
        cursor.execute(adapt_query(select_query), (telegram_id, game_type))
        record = cursor.fetchone()

        if record:
            new_count = record['count'] + count_increment
            update_query = "UPDATE score_logs SET count = ? WHERE telegram_id = ? AND game_type = ?;"
            cursor.execute(adapt_query(update_query), (new_count, telegram_id, game_type))
        else:
            insert_query = "INSERT INTO score_logs (telegram_id, game_type, count) VALUES (?, ?, ?);"
            cursor.execute(adapt_query(insert_query), (telegram_id, game_type, count_increment))

        connection.commit()
    except Exception as error:
        connection.rollback()
        logger.error(f"Failed performance telemetry logging sequence block execution: {error}")
    finally:
        cursor.close()
        connection.close()

# ==============================================================================
# COMPETITIVE MULTIPLAYER ASYNC DUEL LINK SCHEDULING INTERFACES
# ==============================================================================

def create_duel_link(player_id: int, opponent_id: int, initial_status: str = "pending") -> int:
    """
    Registers asynchronous offline duel link structures across multiplayer lobbies.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    created_id = -1
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        if IS_POSTGRES:
            query = """
                INSERT INTO duel_links (player_id, opponent_id, status, created_at)
                VALUES (%s, %s, %s, %s) RETURNING id;
            """
            cursor.execute(query, (player_id, opponent_id, initial_status, now_str))
            created_id = cursor.fetchone()[0]
        else:
            query = """
                INSERT INTO duel_links (player_id, opponent_id, status, created_at)
                VALUES (?, ?, ?, ?);
            """
            cursor.execute(adapt_query(query), (player_id, opponent_id, initial_status, now_str))
            created_id = cursor.lastrowid

        connection.commit()
    except Exception as error:
        connection.rollback()
        logger.error(f"Error initializing async multiplayer match parameters: {error}")
    finally:
        cursor.close()
        connection.close()

    return created_id

def get_duel_link(link_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieves match parameters and challenge tracking data details.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    data_payload = None

    try:
        query = "SELECT * FROM duel_links WHERE id = ?;"
        cursor.execute(adapt_query(query), (link_id,))
        record = cursor.fetchone()
        if record:
            data_payload = dict(record)
    except Exception as error:
        logger.error(f"Failed retrieval query for match identity parameter {link_id}: {error}")
    finally:
        cursor.close()
        connection.close()

    return data_payload

def update_duel_link_status(link_id: int, status: str) -> bool:
    """
    Updates the structural processing states of asynchronous duel invitations.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    success = False
    try:
        query = "UPDATE duel_links SET status = ? WHERE id = ?;"
        cursor.execute(adapt_query(query), (status, link_id))
        connection.commit()
        success = True
    except Exception as error:
        connection.rollback()
        logger.error(f"Failed updating operational states on duel vector link index {link_id}: {error}")
    finally:
        cursor.close()
        connection.close()
    return success

# ==============================================================================
# LIVE CAMPAIGN EVENTS ENGINE
# ==============================================================================

def manage_active_event(event_id: int, name: str, closing_time: str, meta: str, r_type: str, r_val: str) -> None:
    """
    Maintains server event metrics inside live content campaign structures.
    """
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # Wipe historic staging variables cleanly
        cursor.execute(adapt_query("DELETE FROM active_event;"))

        insert_query = """
            INSERT INTO active_event (event_id, event_name, end_time, extra_data, reward_type, reward_value)
            VALUES (?, ?, ?, ?, ?, ?);
        """
        cursor.execute(adapt_query(insert_query), (event_id, name, closing_time, meta, r_type, r_val))
        connection.commit()
        logger.info(f"Campaign tracking engine shifted configurations to active node: '{name}'")
    except Exception as error:
        connection.rollback()
        logger.error(f"Encountered mutation lock failure inside content scheduling matrices: {error}")
    finally:
        cursor.close()
        connection.close()

def get_active_event() -> Optional[Dict[str, Any]]:
    """
    Queries current operations parameter models from storage schemas.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    event_packet = None

    try:
        cursor.execute(adapt_query("SELECT * FROM active_event LIMIT 1;"))
        record = cursor.fetchone()
        if record:
            event_packet = dict(record)
    except Exception as error:
        logger.error(f"Error handling queries on tracking layouts for active events: {error}")
    finally:
        cursor.close()
        connection.close()

    return event_packet

# ==============================================================================
# USER ASSET HOARD & INVENTORY SYSTEM OVERVIEW
# ==============================================================================

def get_user_items(telegram_id: int) -> List[Dict[str, Any]]:
    """
    Lists all market purchases assigned to a specific account profile.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    items_list = []

    try:
        query = "SELECT * FROM user_items WHERE telegram_id = ? ORDER BY id DESC;"
        cursor.execute(adapt_query(query), (telegram_id,))
        records = cursor.fetchall()
        items_list = [dict(row) for row in records]
    except Exception as error:
        logger.error(f"Error pulling inventory details for profile reference ID {telegram_id}: {error}")
    finally:
        cursor.close()
        connection.close()

    return items_list

def get_user_titles(telegram_id: int) -> List[str]:
    """
    Returns all titles unlocked by the user for title customization features.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    titles = []

    try:
        query = "SELECT DISTINCT title_name FROM user_titles WHERE telegram_id = ?;"
        cursor.execute(adapt_query(query), (telegram_id,))
        records = cursor.fetchall()
        titles = [row['title_name'] for row in records]
    except Exception as error:
        logger.error(f"Error processing inventory asset title lookups for target tracking ID {telegram_id}: {error}")
    finally:
        cursor.close()
        connection.close()

    return titles

# ==============================================================================
# INFINITY RANK ELITE DIVISION LEADERBOARD CACHING LAYER
# ==============================================================================

def update_infinity_ranks(external_cursor=None, external_conn=None) -> None:
    """
    Caches the top 10 legendary players into a separate dedicated table 
    to maximize dashboard rendering efficiency.
    """
    cursor = external_cursor
    connection = external_conn
    close_at_end = False

    if cursor is None or connection is None:
        connection = get_db_connection()
        cursor = connection.cursor()
        close_at_end = True

    try:
        # Fetch current top 10 players based on active performance rankings
        cursor.execute(adapt_query("SELECT telegram_id, username, score FROM users ORDER BY score DESC LIMIT 10;"))
        elite_players = cursor.fetchall()

        # Clear old rows securely
        cursor.execute(adapt_query("DELETE FROM infinity_rank;"))

        # Repopulate the elite rank cache table
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        insert_query = "INSERT INTO infinity_rank (telegram_id, username, score, updated_at) VALUES (?, ?, ?, ?);"
        
        for player in elite_players:
            cursor.execute(adapt_query(insert_query), (player['telegram_id'], player['username'], player['score'], now_str))

        if close_at_end:
            connection.commit()

    except Exception as error:
        if close_at_end:
            connection.rollback()
        logger.error(f"Failed to synchronize cache records inside infinity tier tables: {error}")
    finally:
        if close_at_end:
            cursor.close()
            connection.close()

def get_infinity_ranks() -> List[Dict[str, Any]]:
    """
    Retrieves the cached elite leaderboard entries instantly.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    elite_dataset = []

    try:
        cursor.execute(adapt_query("SELECT * FROM infinity_rank ORDER BY score DESC;"))
        records = cursor.fetchall()
        elite_dataset = [dict(row) for row in records]
    except Exception as error:
        logger.error(f"Failed to load cached division rankings matrix indices: {error}")
    finally:
        cursor.close()
        connection.close()

    return elite_dataset
