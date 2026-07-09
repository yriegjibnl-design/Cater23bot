import os
import sys
import json
import sqlite3
import logging
import traceback
import time
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Any, Dict, List, Optional, Union, Generator
import random
import string
import threading

# ==============================================================================
# DATABASE CONFIGURATION & ENVIRONMENT SETUP
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("DatabaseManager")

DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
DB_FILE: str = "club_tas.db"
OLD_DB_FILE: str = "game_database.db"

# Thread-safe global state structures
_cache_lock = threading.Lock()
_sqlite_thread_lock = threading.Lock()
_local_context = threading.local()
pg_pool: Optional[pool.SimpleConnectionPool] = None

if DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")):
    IS_POSTGRES = True
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    logger.info("Database Mode: Production PostgreSQL detected via environment variable.")
    
    try:
        ssl_mode = os.getenv("DB_SSL_MODE", "allow")
        pg_pool = pool.SimpleConnectionPool(
            minconn=2,
            maxconn=30,
            dsn=DATABASE_URL,
            sslmode=ssl_mode
        )
        logger.info("PostgreSQL SimpleConnectionPool initialized successfully with thread safety.")
    except Exception as initialization_error:
        logger.critical(f"Failed to initialize PostgreSQL pool: {initialization_error}")
        raise initialization_error
else:
    IS_POSTGRES = False
    logger.info(f"Database Mode: Local SQLite fallback detected. File pathway: {DB_FILE}")

# ==============================================================================
# ENTERPRISE IN-MEMORY INVALIDING CACHE SYSTEM
# ==============================================================================
class MemoryTTLCache:
    def __init__(self):
        self.store: Dict[str, Tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        with _cache_lock:
            if key in self.store:
                val, expire_time = self.store[key]
                if time.time() < expire_time:
                    return val
                del self.store[key]
        return None

    def set(self, key: str, value: Any, ttl: float = 15.0) -> None:
        with _cache_lock:
            self.store[key] = (value, time.time() + ttl)

    def invalidate(self, tags: List[str]) -> None:
        with _cache_lock:
            keys_to_del = [k for k in self.store if any(tag in k for tag in tags)]
            for k in keys_to_del:
                self.store.pop(k, None)

    def clear(self) -> None:
        with _cache_lock:
            self.store.clear()

global_cache = MemoryTTLCache()

# ==============================================================================
# AUDIT LOGGING HOOKS
# ==============================================================================
def log_audit_event(action_type: str, actor_id: Optional[int], target_id: Optional[Union[int, str]], details: Dict[str, Any]) -> None:
    """Internal helper to drop structured events into the audit tracking table safely."""
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        details_json = json.dumps(details, ensure_ascii=False)
        
        # Build query decoupled from standard wrappers to prevent validation/audit recurse cascades
        query_str = """
            INSERT INTO audit_logs (action_type, actor_id, target_id, details, created_at)
            VALUES (%s, %s, %s, %s, %s);
        """
        adapted_query_str = adapt_query(query_str)
        conn, is_pg = get_db_connection()
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(adapted_query_str, (action_type, actor_id, str(target_id) if target_id else None, details_json, now_str))
            conn.commit()
        except Exception as inner_err:
            if conn:
                conn.rollback()
            logger.error(f"Failed writing directly to audit trails table: {inner_err}")
        finally:
            if cursor:
                cursor.close()
            release_db_connection(conn, is_pg)
    except Exception as general_audit_err:
        logger.error(f"Audit log generator crashed silently to ensure transaction safety: {general_audit_err}")

# ==============================================================================
# TRANSACTIONAL CONTEXT MANAGER (ADVANCED WORKER ENGINE)
# ==============================================================================
class DBTransactionContext:
    """
    Guarantees atomic multi-statement operations, automatic rollback processing,
    and thread isolation via thread-local variable context tracking.
    """
    def __init__(self):
        self.conn = None
        self.is_pg = False
        self.cursor = None

    def __enter__(self):
        if getattr(_local_context, "active_conn", None) is not None:
            raise RuntimeError("Nested database transactions are blocked on this architecture thread model.")
        
        self.conn, self.is_pg = get_db_connection()
        if not self.is_pg:
            _sqlite_thread_lock.acquire()
            
        self.conn.autocommit = False
        if self.is_pg:
            self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        else:
            self.cursor = self.conn.cursor()
            
        _local_context.active_conn = self.conn
        _local_context.active_cursor = self.cursor
        _local_context.is_pg = self.is_pg
        return self

    def execute(self, query: str, params: tuple = ()) -> Any:
        start_time = time.perf_counter()
        adapted = adapt_query(query)
        try:
            self.cursor.execute(adapted, params)
            duration = time.perf_counter() - start_time
            if duration > 0.100:
                logger.warning(f"[SLOW TRANSACTION QUERY ALERT] Execution time: {duration:.4f}s | Query: {adapted}")
            return self.cursor
        except Exception as transaction_stmt_err:
            logger.error(f"Statement execution failure inside transaction boundary: {transaction_stmt_err}")
            raise transaction_stmt_err

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is not None:
                logger.warning(f"Exception intercepted within transaction execution flow. Initializing rollback... Reason: {exc_val}")
                self.conn.rollback()
            else:
                self.conn.commit()
        except Exception as boundary_err:
            logger.error(f"Critical error managing transaction end bounds: {boundary_err}")
            raise boundary_err
        finally:
            if self.cursor:
                self.cursor.close()
            _local_context.active_conn = None
            _local_context.active_cursor = None
            _local_context.is_pg = False
            
            conn_ref = self.conn
            is_pg_ref = self.is_pg
            self.conn = None
            self.cursor = None
            
            if not is_pg_ref:
                _sqlite_thread_lock.release()
            release_db_connection(conn_ref, is_pg_ref)

def transaction_scope() -> DBTransactionContext:
    """Returns a fresh transaction context manager scope instance."""
    return DBTransactionContext()

# ==============================================================================
# CROSS-DATABASE COMPATIBILITY ADAPTERS & TRANSIENT RETRY LAYER
# ==============================================================================

def adapt_query(query_string: str) -> str:
    """
    Translates standard placeholder tokens to ensure 100% interoperability 
    between SQLite engine tokens (?) and PostgreSQL engine tokens (%s).
    """
    if IS_POSTGRES:
        return query_string.replace("?", "%s")
    else:
        return query_string.replace("%s", "?")

def get_db_connection() -> Any:
    """
    Establishes and returns a structured database connection object matching 
    the active infrastructure context (PostgreSQL or SQLite) with transaction safety.
    """
    max_retries = 5
    retry_delay = 0.5
    
    if getattr(_local_context, "active_conn", None) is not None:
        return _local_context.active_conn, _local_context.is_pg
        
    for attempt in range(max_retries):
        try:
            if IS_POSTGRES:
                if pg_pool is None:
                    raise psycopg2.OperationalError("PostgreSQL pool is uninitialized.")
                try:
                    connection = pg_pool.getconn()
                    # Verify connection fitness on extraction
                    with connection.cursor() as t_cur:
                        t_cur.execute("SELECT 1;")
                except (psycopg2.OperationalError, psycopg2.InterfaceError):
                    logger.warning("Extracted a dead PostgreSQL connection thread from pool. Recycling resource...")
                    if pg_pool:
                        try:
                            pg_pool.putconn(connection, close=True)
                        except Exception:
                            pass
                    connection = pg_pool.getconn()
                connection.autocommit = False
                return connection, True
            else:
                connection = sqlite3.connect(DB_FILE, timeout=45.0, check_same_thread=False)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA journal_mode=WAL;")
                connection.execute("PRAGMA foreign_keys=ON;")
                connection.execute("PRAGMA synchronous=NORMAL;")
                connection.execute("PRAGMA cache_size=-64000;")
                connection.execute("PRAGMA temp_store=MEMORY;")
                connection.execute("PRAGMA busy_timeout=45000;")
                return connection, False
        except (psycopg2.OperationalError, sqlite3.OperationalError) as transient_error:
            if attempt < max_retries - 1:
                logger.warning(f"Transient database connection failure (Attempt {attempt + 1}/{max_retries}): {transient_error}. Retrying...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logger.critical(f"Fatal connection collapse after {max_retries} programmatic attempts: {transient_error}")
                raise transient_error
        except Exception as unforeseen_error:
            logger.critical(f"Unforeseen connection acquisition anomaly: {unforeseen_error}")
            raise unforeseen_error

def get_connection() -> Any:
    conn, is_pg = get_db_connection()
    return conn

def release_db_connection(conn: Any, is_pg: bool) -> None:
    """Safely disposes or returns the connection infrastructure back to the manager resource pool."""
    if not conn:
        return
    if getattr(_local_context, "active_conn", None) is not None:
        return  # Connection is bound to an active structural execution scope transaction block
    if is_pg:
        try:
            if pg_pool:
                pg_pool.putconn(conn)
        except Exception as release_error:
            logger.error(f"Error restoring connection back to PostgreSQL resource pool: {release_error}")
    else:
        try:
            conn.close()
        except Exception as close_error:
            logger.error(f"Error terminating local SQLite database resource handle: {close_error}")

# ==============================================================================
# UNIFIED EXECUTION LAYER (SAFE TRANSACTIONS & LEAK PROOF WITH PROFILES)
# ==============================================================================

def execute_write(query: str, params: tuple = ()) -> int:
    """Executes a write query (INSERT, UPDATE, DELETE) safely with automatic rollbacks."""
    if getattr(_local_context, "active_conn", None) is not None:
        start_time = time.perf_counter()
        adapted = adapt_query(query)
        _local_context.active_cursor.execute(adapted, params)
        affected = _local_context.active_cursor.rowcount
        duration = time.perf_counter() - start_time
        if duration > 0.100:
            logger.warning(f"[SLOW WRITE QUERY ALERT] Execution time: {duration:.4f}s | Query: {adapted}")
        return affected if affected is not None else 0

    start_time = time.perf_counter()
    adapted_query_str = adapt_query(query)
    conn, is_pg = get_db_connection()
    cursor = None
    if not is_pg:
        _sqlite_thread_lock.acquire()
    try:
        cursor = conn.cursor()
        cursor.execute(adapted_query_str, params)
        conn.commit()
        affected = cursor.rowcount
        duration = time.perf_counter() - start_time
        if duration > 0.100:
            logger.warning(f"[SLOW WRITE QUERY ALERT] Execution time: {duration:.4f}s | Query: {adapted_query_str}")
        logger.debug(f"Write complete. Rows affected: {affected} | Timing: {duration:.4f}s")
        return affected if affected is not None else 0
    except Exception as write_error:
        duration = time.perf_counter() - start_time
        logger.error(f"Database write crash after {duration:.4f}s: {write_error} | Traceback:\n{traceback.format_exc()} | Query: {adapted_query_str}")
        if conn:
            try:
                conn.rollback()
                logger.info("Database write state rolled back successfully.")
            except Exception as rollback_err:
                logger.error(f"Failed transaction recovery rollback: {rollback_err}")
        return 0
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if not is_pg:
            _sqlite_thread_lock.release()
        release_db_connection(conn, is_pg)

def execute_read_one(query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    """Executes a read query and returns a single row as a standardized dictionary."""
    if getattr(_local_context, "active_conn", None) is not None:
        start_time = time.perf_counter()
        adapted = adapt_query(query)
        _local_context.active_cursor.execute(adapted, params)
        row = _local_context.active_cursor.fetchone()
        duration = time.perf_counter() - start_time
        if duration > 0.100:
            logger.warning(f"[SLOW READ ONE QUERY ALERT] Execution time: {duration:.4f}s | Query: {adapted}")
        if row and not _local_context.is_pg:
            return dict(row)
        return dict(row) if row else None

    start_time = time.perf_counter()
    adapted_query_str = adapt_query(query)
    conn, is_pg = get_db_connection()
    cursor = None
    if not is_pg:
        _sqlite_thread_lock.acquire()
    try:
        if is_pg:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = conn.cursor()
            
        cursor.execute(adapted_query_str, params)
        row = cursor.fetchone()
        duration = time.perf_counter() - start_time
        if duration > 0.100:
            logger.warning(f"[SLOW READ ONE QUERY ALERT] Execution time: {duration:.4f}s | Query: {adapted_query_str}")
        logger.debug(f"Read one complete | Timing: {duration:.4f}s")
        
        if row and not is_pg:
            return dict(row)
        return dict(row) if row else None
    except Exception as read_error:
        duration = time.perf_counter() - start_time
        logger.error(f"Database read one exception after {duration:.4f}s: {read_error} | Traceback:\n{traceback.format_exc()} | Query: {adapted_query_str}")
        return None
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if not is_pg:
            _sqlite_thread_lock.release()
        release_db_connection(conn, is_pg)

def execute_read_all(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Executes a read query and returns all matching rows as a list of dictionaries."""
    if getattr(_local_context, "active_conn", None) is not None:
        start_time = time.perf_counter()
        adapted = adapt_query(query)
        _local_context.active_cursor.execute(adapted, params)
        rows = _local_context.active_cursor.fetchall()
        duration = time.perf_counter() - start_time
        if duration > 0.100:
            logger.warning(f"[SLOW READ ALL QUERY ALERT] Execution time: {duration:.4f}s | Query: {adapted}")
        if not _local_context.is_pg:
            return [dict(r) for r in rows]
        return [dict(r) for r in rows] if rows else []

    start_time = time.perf_counter()
    adapted_query_str = adapt_query(query)
    conn, is_pg = get_db_connection()
    cursor = None
    if not is_pg:
        _sqlite_thread_lock.acquire()
    try:
        if is_pg:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = conn.cursor()
            
        cursor.execute(adapted_query_str, params)
        rows = cursor.fetchall()
        duration = time.perf_counter() - start_time
        if duration > 0.100:
            logger.warning(f"[SLOW READ ALL QUERY ALERT] Execution time: {duration:.4f}s | Query: {adapted_query_str}")
        logger.debug(f"Read all fetched {len(rows)} elements | Timing: {duration:.4f}s")
        
        if not is_pg:
            return [dict(r) for r in rows]
        return [dict(r) for r in rows] if rows else []
    except Exception as read_all_error:
        duration = time.perf_counter() - start_time
        logger.error(f"Database read all exception after {duration:.4f}s: {read_all_error} | Traceback:\n{traceback.format_exc()} | Query: {adapted_query_str}")
        return []
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if not is_pg:
            _sqlite_thread_lock.release()
        release_db_connection(conn, is_pg)

# ==============================================================================
# ENTERPRISE DATA VALIDATION HOOK ENGINE
# ==============================================================================
def validate_write_operation(table_name: str, fields: Dict[str, Any]) -> None:
    """Pre-commit pipeline structural engine validating data safety bounds."""
    if "score" in fields and fields["score"] is not None and int(fields["score"]) < 0:
        raise ValueError("Enterprise Data Constraint Breach: User score parameter cannot register negative integers.")
    if "rank" in fields and fields["rank"] is not None:
        if not str(fields["rank"]).strip():
            raise ValueError("Enterprise Data Constraint Breach: System rank designations cannot string empty configurations.")
    if "title" in fields and fields["title"] is not None and not str(fields["title"]).strip():
        raise ValueError("Enterprise Data Constraint Breach: Set title constraints cannot accept empty strings.")
    if "title_name" in fields and fields["title_name"] is not None and not str(fields["title_name"]).strip():
        raise ValueError("Enterprise Data Constraint Breach: Item title properties must hold visual identities.")
    if "duration_hours" in fields and fields["duration_hours"] is not None and int(fields["duration_hours"]) < 0:
        raise ValueError("Enterprise Data Constraint Breach: Dynamic configuration duration_hours properties cannot scale negative spans.")
    if "max_uses" in fields and fields["max_uses"] is not None and int(fields["max_uses"]) < 0:
        raise ValueError("Enterprise Data Constraint Breach: Redeem code uses properties cannot hold sub-zero configurations.")

# ==============================================================================
# JSON SERIALIZATION COMPATIBILITY TOOLS
# ==============================================================================
def safe_json_serialize(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception as serialize_err:
        logger.error(f"Corrupted application object dropped out JSON pipeline. Repairing automatically... Error: {serialize_err}")
        return "[]"

def safe_json_deserialize(raw_str: Any) -> Any:
    if not raw_str:
        return []
    if not isinstance(raw_str, str):
        return raw_str
    try:
        return json.loads(raw_str)
    except Exception as parse_error:
        logger.warning(f"Corrupted data intercepted inside JSON deserialize wrapper. Executing repair... Value: {raw_str} | Error: {parse_error}")
        # Programmatic healing of structural configurations
        clean_str = raw_str.strip()
        if not clean_str or clean_str in ["null", "None", "''", '""']:
            return []
        if not clean_str.startswith("[") and not clean_str.startswith("{"):
            return [clean_str]
        return []

# ==============================================================================
# DYNAMIC SCHEMA MIGRATION SYSTEM
# ==============================================================================
def execute_dynamic_migrations(cursor, is_pg: bool) -> None:
    """Performs programmatic metadata discovery and dynamically executes missing schema adjustments."""
    logger.info("Executing operational schema structural audit pass...")
    
    # Core system verification tracking structural column modifications
    expected_mutations = {
        "users": [
            ("unlocked_titles", "JSONB" if is_pg else "TEXT", "DEFAULT '[]'"),
            ("unlocked_perks", "JSONB" if is_pg else "TEXT", "DEFAULT '[]'"),
            ("player_status", "VARCHAR(50)" if is_pg else "TEXT", "DEFAULT 'idle'"),
            ("current_duel_id", "INT" if is_pg else "INTEGER", "DEFAULT NULL")
        ],
        "shop": [
            ("item_type", "VARCHAR(50)" if is_pg else "TEXT", "DEFAULT 'title'")
        ]
    }
    
    for table_name, schema_mutations in expected_mutations.items():
        existing_columns = set()
        try:
            if is_pg:
                cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table_name}';")
                existing_columns = {r[0].lower() for r in cursor.fetchall()}
            else:
                cursor.execute(f"PRAGMA table_info({table_name});")
                existing_columns = {r[1].lower() for r in cursor.fetchall()}
        except Exception as query_meta_err:
            logger.warning(f"Metadata parsing skipped for structural target '{table_name}': {query_meta_err}")
            continue

        if not existing_columns:
            continue  # Table does not exist yet; handled seamlessly by baseline initialization queries
            
        for column_name, data_type, default_expr in schema_mutations:
            if column_name.lower() not in existing_columns:
                logger.info(f"[SCHEMA MIGRATION EVENT] Injecting missing structural mutation '{column_name}' into architecture target '{table_name}'")
                alter_q = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {data_type} {default_expr};"
                try:
                    cursor.execute(alter_q)
                except Exception as alter_err:
                    logger.error(f"Failed altering structural model definitions for column '{column_name}': {alter_err}")

# ==============================================================================
# DATABASE SCHEMA INITIALIZATION & MIGRATION ORCHESTRATION
# ==============================================================================

def init_db(initial_admin_id: int = 7430881772) -> None:
    """
    Creates all necessary application tables with appropriate constraints, 
    indexes, and default rows. Fully matches all combined production attributes.
    """
    logger.info("Beginning database architectural setup and schema verification...")
    conn, is_pg = get_db_connection()
    cursor = conn.cursor()
    if not is_pg:
        _sqlite_thread_lock.acquire()
    try:
        # Base implementation of audit tracking architecture
        if is_pg:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id SERIAL PRIMARY KEY,
                    action_type VARCHAR(100),
                    actor_id BIGINT,
                    target_id VARCHAR(255),
                    details JSONB,
                    created_at VARCHAR(50)
                );
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT,
                    actor_id INTEGER,
                    target_id TEXT,
                    details TEXT,
                    created_at TEXT
                );
            """)

        if is_pg:
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
                    last_seen VARCHAR(50),
                    player_status VARCHAR(50) DEFAULT 'idle',
                    current_duel_id INT DEFAULT NULL,
                    unlocked_titles JSONB DEFAULT '[]',
                    unlocked_perks JSONB DEFAULT '[]'
                );
            """)
            # 2. Admins Table
            cursor.execute("CREATE TABLE IF NOT EXISTS admins (telegram_id BIGINT PRIMARY KEY);")
            # 3. Dice History Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dice_history (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                    dice_value INT,
                    rolled_at VARCHAR(50)
                );
            """)
            # 4. Score Logs Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS score_logs (
                    telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
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
                    category VARCHAR(50),
                    item_type VARCHAR(50) DEFAULT 'title'
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
                    telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                    code VARCHAR(255) REFERENCES redeem_codes(code) ON DELETE CASCADE,
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
                    player_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                    opponent_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                    status VARCHAR(50),
                    created_at VARCHAR(50),
                    winner_id BIGINT DEFAULT NULL
                );
            """)
            # 10. User Items Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_items (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                    item_name VARCHAR(255),
                    purchased_at VARCHAR(50)
                );
            """)
            # 11. User Titles Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_titles (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                    title_name VARCHAR(255),
                    unlocked_at VARCHAR(50)
                );
            """)
            # 12. Infinity Rank Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS infinity_rank (
                    telegram_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
                    username VARCHAR(255),
                    score INT,
                    updated_at VARCHAR(50)
                );
            """)
            # 13. Offline Duels Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS offline_duels (
                    duel_id VARCHAR(255) PRIMARY KEY,
                    creator_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                    wager INT,
                    rounds INT,
                    status VARCHAR(50) DEFAULT 'pending',
                    created_at VARCHAR(50)
                );
            """)
        else:
            # SQLite Sequence
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
                    last_seen TEXT,
                    player_status TEXT DEFAULT 'idle',
                    current_duel_id INTEGER DEFAULT NULL,
                    unlocked_titles TEXT DEFAULT '[]',
                    unlocked_perks TEXT DEFAULT '[]'
                );
            """)
            cursor.execute("CREATE TABLE IF NOT EXISTS admins (telegram_id INTEGER PRIMARY KEY);")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dice_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER REFERENCES users(telegram_id) ON DELETE CASCADE,
                    dice_value INTEGER,
                    rolled_at TEXT
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS score_logs (
                    telegram_id INTEGER REFERENCES users(telegram_id) ON DELETE CASCADE,
                    game_type TEXT,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (telegram_id, game_type)
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shop (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title_name TEXT UNIQUE,
                    cost INTEGER,
                    category TEXT,
                    item_type TEXT DEFAULT 'title'
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS redeem_codes (
                    code TEXT PRIMARY KEY,
                    title_name TEXT,
                    max_uses INTEGER,
                    current_uses INTEGER DEFAULT 0,
                    duration_hours INTEGER
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS redeem_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER REFERENCES users(telegram_id) ON DELETE CASCADE,
                    code TEXT REFERENCES redeem_codes(code) ON DELETE CASCADE,
                    used_at TEXT
                );
            """)
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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS duel_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER REFERENCES users(telegram_id) ON DELETE CASCADE,
                    opponent_id INTEGER REFERENCES users(telegram_id) ON DELETE CASCADE,
                    status TEXT,
                    created_at TEXT,
                    winner_id INTEGER DEFAULT NULL
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER REFERENCES users(telegram_id) ON DELETE CASCADE,
                    item_name TEXT,
                    purchased_at TEXT
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_titles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER REFERENCES users(telegram_id) ON DELETE CASCADE,
                    title_name TEXT,
                    unlocked_at TEXT
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS infinity_rank (
                    telegram_id INTEGER PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
                    username TEXT,
                    score INTEGER,
                    updated_at TEXT
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS offline_duels (
                    duel_id TEXT PRIMARY KEY,
                    creator_id INTEGER REFERENCES users(telegram_id) ON DELETE CASCADE,
                    wager INTEGER,
                    rounds INTEGER,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT
                );
            """)

        # Dynamically structural alteration scans protecting existing system deployments
        execute_dynamic_migrations(cursor, is_pg)

        # Performance Indexes Optimization for Enterprise High-Concurrency
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_score ON users(score DESC, total_games DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_dice_history_uid ON dice_history(telegram_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_items_uid ON user_items(telegram_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_titles_uid ON user_titles(telegram_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_redeem_hist_code ON redeem_history(code);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_duel_links_players ON duel_links(player_id, opponent_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_type ON audit_logs(action_type);")

        # Admin Seeding
        admin_q = "INSERT INTO admins (telegram_id) VALUES (?) ON CONFLICT (telegram_id) DO NOTHING;"
        cursor.execute(adapt_query(admin_q), (initial_admin_id,))
        conn.commit()

        # Seed standard store items
        cursor.execute(adapt_query("SELECT COUNT(*) FROM shop;"))
        if cursor.fetchone()[0] == 0:
            default_items = [
                ('🥈 نوچه کلوب', 200, 'normal', 'title'),
                ('🥈 تاس باز', 400, 'normal', 'title'),
                ('🔮 شکارچی سایه', 1500, 'epic', 'title'),
                ('🔮 مبارز ابدی', 2500, 'epic', 'title'),
                ('👑 شاهزاده نبرد', 6000, 'legendary', 'title'),
                ('👑 گلادیاتور اعظم', 9000, 'legendary', 'title')
            ]
            insert_q = "INSERT INTO shop (title_name, cost, category, item_type) VALUES (?, ?, ?, ?) ON CONFLICT (title_name) DO NOTHING;"
            for item in default_items:
                cursor.execute(adapt_query(insert_q), item)
            conn.commit()

        if is_pg:
            migrate_old_sqlite_data(cursor, conn)

    except Exception as error:
        conn.rollback()
        logger.error(f"Critical error occurred during schema initialization: {error} | Traceback:\n{traceback.format_exc()}")
    finally:
        cursor.close()
        if not is_pg:
            _sqlite_thread_lock.release()
        release_db_connection(conn, is_pg)

def init_db_schema() -> None:
    init_db(7430881772)

def migrate_old_sqlite_data(pg_cursor, pg_conn) -> None:
    if os.path.exists(OLD_DB_FILE) and os.path.getsize(OLD_DB_FILE) > 0 and IS_POSTGRES:
        try:
            sqlite_conn = sqlite3.connect(OLD_DB_FILE)
            sqlite_cursor = sqlite_conn.cursor()
            sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in sqlite_cursor.fetchall()]
            
            all_tables = ["users", "admins", "dice_history", "score_logs", "shop", "redeem_codes", "redeem_history", "active_event", "duel_links", "user_items", "user_titles", "infinity_rank", "offline_duels"]
            
            for t_name in all_tables:
                if t_name in tables:
                    sqlite_cursor.execute(f"SELECT * FROM {t_name};")
                    cols = [d[0] for d in sqlite_cursor.description]
                    rows = sqlite_cursor.fetchall()
                    if not rows:
                        continue
                    
                    placeholders = ", ".join(["%s"] * len(cols))
                    col_names = ", ".join(cols)
                    
                    pg_cursor.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{t_name}';")
                    pg_cols_info = {r[0]: r[1] for r in pg_cursor.fetchall()}
                    
                    for row in rows:
                        vals = list(row)
                        for i, col in enumerate(cols):
                            if pg_cols_info.get(col) == "jsonb" and isinstance(vals[i], str):
                                vals[i] = json.dumps(safe_json_deserialize(vals[i]), ensure_ascii=False)
                        
                        if t_name == "users":
                            conflict_clause = "ON CONFLICT (telegram_id) DO NOTHING"
                        elif t_name == "admins":
                            conflict_clause = "ON CONFLICT (telegram_id) DO NOTHING"
                        elif t_name == "score_logs":
                            conflict_clause = "ON CONFLICT (telegram_id, game_type) DO NOTHING"
                        elif t_name == "shop":
                            conflict_clause = "ON CONFLICT (title_name) DO NOTHING"
                        elif t_name == "redeem_codes":
                            conflict_clause = "ON CONFLICT (code) DO NOTHING"
                        elif t_name == "infinity_rank":
                            conflict_clause = "ON CONFLICT (telegram_id) DO NOTHING"
                        elif t_name == "offline_duels":
                            conflict_clause = "ON CONFLICT (duel_id) DO NOTHING"
                        else:
                            conflict_clause = "ON CONFLICT (id) DO NOTHING" if "id" in cols else ""
                        
                        q = f"INSERT INTO {t_name} ({col_names}) VALUES ({placeholders}) {conflict_clause};"
                        try:
                            pg_cursor.execute(q, tuple(vals))
                        except Exception as row_err:
                            logger.error(f"[MIGRATION DATA FAILURE SKIP] Recoverable anomaly in data block entry of '{t_name}': {row_err}")
                            continue
            
            for t_name in all_tables:
                if t_name in ["dice_history", "shop", "redeem_history", "active_event", "duel_links", "user_items", "user_titles"]:
                    pg_cursor.execute(f"SELECT exists(SELECT 1 FROM information_schema.sequences WHERE sequence_name='{t_name}_id_seq');")
                    if pg_cursor.fetchone()[0]:
                        pg_cursor.execute(f"SELECT setval('{t_name}_id_seq', COALESCE((SELECT MAX(id)+1 FROM {t_name}), 1), false);")
                        
            pg_conn.commit()
            logger.info("Successfully migrated all old SQLite history tables and synchronized serial sequences to PostgreSQL.")
            sqlite_conn.close()
        except Exception as e:
            logger.error(f"Migration architectural failure: {e} | Traceback:\n{traceback.format_exc()}")

def seed_shop_items() -> None:
    items = [
        ("دوئل ۵ تا راند", 2000, "legendary", "perk_rounds"),
        ("XP سقف شرط +۵۰", 3500, "legendary", "perk_wager"),
        ("تاس شانس", 5000, "legendary", "perk_luckydice"),
        ("گلادیاتور نوپا", 200, "normal", "title"),
        ("ولخرجی شب", 600, "epic", "title"),
        ("الماس برتر", 1200, "legendary", "title")
    ]
    query = "INSERT INTO shop (title_name, cost, category, item_type) VALUES (%s, %s, %s, %s) ON CONFLICT (title_name) DO NOTHING;"
    for name, cost, cat, itype in items:
        validate_write_operation("shop", {"title_name": name, "cost": cost})
        execute_write(query, (name, cost, cat, itype))

# ==============================================================================
# PRO-GRADE HEALTH CHECK ENGINE
# ==============================================================================

def perform_health_check() -> bool:
    """Verifies operational state of database connectivity and transactional loops."""
    try:
        res = execute_read_one("SELECT 1 AS status;")
        if res is None or int(res.get("status", 0)) != 1:
            return False
            
        # Verify transaction isolation integrity loops programmatically
        try:
            with transaction_scope() as tx:
                tx.execute("SELECT 1;")
        except Exception:
            logger.error("Health Check Warning: Dedicated transaction contextual scopes failing.")
            return False

        if IS_POSTGRES and pg_pool:
            logger.info(f"[HEALTH PROFILE] PostgreSQL Connection Pool Status -> Min: {pg_pool.minconn}, Max: {pg_pool.maxconn}")
        else:
            res_wal = execute_read_one("PRAGMA journal_mode;")
            logger.info(f"[HEALTH PROFILE] Local SQLite Engine State -> Journal Mode: {res_wal.get('journal_mode') if res_wal else 'Unknown'}")
            
        return True
    except Exception as health_err:
        logger.error(f"Database infrastructure health diagnostics failure: {health_err} | Trace:\n{traceback.format_exc()}")
        return False

# ==============================================================================
# ENGINE DEALLOCATION GRACEFUL SHUTDOWN
# ==============================================================================
def graceful_shutdown() -> None:
    """Ensures absolute cleanup of connection wrappers preventing leaks on app reload sequences."""
    global pg_pool
    logger.info("Initializing runtime environment termination sequence...")
    if IS_POSTGRES and pg_pool:
        try:
            pg_pool.closeall()
            logger.info("PostgreSQL thread pooling references terminated safely.")
        except Exception as pool_err:
            logger.error(f"Error wrapping up PostgreSQL enterprise pool elements: {pool_err}")
    global_cache.clear()

# ==============================================================================
# BOT BUSINESS LOGIC WRAPPER API FUNCTIONS
# ==============================================================================

def calculate_rank(score: int) -> str:
    RANKS = [
        (14000, "🌌 Infinity"),
        (10000, "🏆 Grandmaster"),
        (7000, "💎 Diamond"),
        (4000, "🥇 Gold"),
        (1500, "🥈 Silver")
    ]
    for limit, title in RANKS:
        if score >= limit:
            return title
    return "🥉 Bronze I"

def is_user_admin(telegram_id: Union[int, str]) -> bool:
    row = execute_read_one("SELECT 1 FROM admins WHERE telegram_id = %s", (int(telegram_id),))
    return row is not None or int(telegram_id) == 7430881772

def get_top_10_ids() -> List[int]:
    cache_key = "system_top_10_ids"
    cached_val = global_cache.get(cache_key)
    if cached_val is not None:
        return cached_val
        
    rows = execute_read_all("SELECT telegram_id FROM users ORDER BY score DESC, total_games DESC LIMIT 10")
    result = [int(r['telegram_id']) for r in rows] if rows else []
    global_cache.set(cache_key, result, ttl=20.0)
    return result

def get_or_create_user(telegram_id: int, username: str) -> Optional[Dict[str, Any]]:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    conn, is_pg = get_db_connection()
    cursor = None
    if not is_pg:
        _sqlite_thread_lock.acquire()
    try:
        if is_pg:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            for_update = "SELECT * FROM users WHERE telegram_id = %s FOR UPDATE;"
        else:
            cursor = conn.cursor()
            for_update = "SELECT * FROM users WHERE telegram_id = %s;"
            
        cursor.execute(adapt_query(for_update), (telegram_id,))
        raw_user = cursor.fetchone()
        
        if not raw_user:
            if is_pg:
                ins_q = """
                    INSERT INTO users (telegram_id, username, score, rank, title, created_at, last_seen, unlocked_titles, unlocked_perks)
                    VALUES (%s, %s, 0, '🥉 Bronze I', 'بدون لقب', %s, %s, '[]'::jsonb, '[]'::jsonb)
                    ON CONFLICT (telegram_id) DO NOTHING;
                """
            else:
                ins_q = """
                    INSERT INTO users (telegram_id, username, score, rank, title, created_at, last_seen, unlocked_titles, unlocked_perks)
                    VALUES (%s, %s, 0, '🥉 Bronze I', 'بدون لقب', %s, %s, '[]', '[]')
                    ON CONFLICT (telegram_id) DO NOTHING;
                """
            cursor.execute(adapt_query(ins_q), (telegram_id, username, now_str, now_str))
            conn.commit()
            cursor.execute(adapt_query(for_update), (telegram_id,))
            raw_user = cursor.fetchone()
            
            # Post-commit non-blocking logging hooks
            log_audit_event("user_registration", telegram_id, telegram_id, {"username": username, "status": "success"})
            global_cache.invalidate(["users_top_players", "system_top_10_ids"])
        else:
            upd_q = "UPDATE users SET last_seen = %s, username = %s WHERE telegram_id = %s;"
            cursor.execute(adapt_query(upd_q), (now_str, username, telegram_id))
            conn.commit()
            cursor.execute(adapt_query(for_update), (telegram_id,))
            raw_user = cursor.fetchone()
            
        if not raw_user:
            return None
            
        user = dict(raw_user)
        
        # System structural handling parsing cross-database variables safely
        if is_pg:
            if 'unlocked_titles' in user and not isinstance(user['unlocked_titles'], str) and user['unlocked_titles'] is not None:
                user['unlocked_titles'] = json.dumps(user['unlocked_titles'], ensure_ascii=False)
            elif 'unlocked_titles' in user and user['unlocked_titles'] is None:
                user['unlocked_titles'] = '[]'
                
            if 'unlocked_perks' in user and not isinstance(user['unlocked_perks'], str) and user['unlocked_perks'] is not None:
                user['unlocked_perks'] = json.dumps(user['unlocked_perks'], ensure_ascii=False)
            elif 'unlocked_perks' in user and user['unlocked_perks'] is None:
                user['unlocked_perks'] = '[]'
        else:
            # Self repair layer on SQLite raw textual queries returning invalid states
            user['unlocked_titles'] = json.dumps(safe_json_deserialize(user.get('unlocked_titles')), ensure_ascii=False)
            user['unlocked_perks'] = json.dumps(safe_json_deserialize(user.get('unlocked_perks')), ensure_ascii=False)
                
        if int(telegram_id) in get_top_10_ids():
            user['title'] = "GOD OF DICE"
            
        return user
    except Exception as e:
        logger.error(f"Error inside get_or_create_user execution transaction context: {e} | Trace:\n{traceback.format_exc()}")
        if conn:
            conn.rollback()
        return None
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if not is_pg:
            _sqlite_thread_lock.release()
        release_db_connection(conn, is_pg)

def update_stats(telegram_id: int, score_change: int, match_result: str) -> Optional[Dict[str, Any]]:
    conn, is_pg = get_db_connection()
    cursor = None
    if not is_pg:
        _sqlite_thread_lock.acquire()
    try:
        if is_pg:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            for_update = "SELECT * FROM users WHERE telegram_id = %s FOR UPDATE;"
        else:
            cursor = conn.cursor()
            for_update = "SELECT * FROM users WHERE telegram_id = %s;"
            
        cursor.execute(adapt_query(for_update), (telegram_id,))
        raw_user = cursor.fetchone()
        if not raw_user:
            return None
            
        user = dict(raw_user)
        current_score = int(user.get('score', 0))
        
        if current_score >= 10000:
            if match_result == 'win':
                score_change = 80
            elif match_result == 'loss':
                score_change = -100
                
        new_score = max(0, min(14000, current_score + score_change))
        new_rank = calculate_rank(new_score)
        rank_changed = (new_rank != user.get('rank'))
        
        # Structured validation pass
        validate_write_operation("users", {"score": new_score, "rank": new_rank})
        
        w_inc = 1 if match_result == 'win' else 0
        l_inc = 1 if match_result == 'loss' else 0
        d_inc = 1 if match_result == 'draw' else 0
        g_inc = 1 if match_result in ['win', 'loss', 'draw'] else 0
        
        upd_q = """
            UPDATE users 
            SET score = %s, rank = %s, wins = wins + %s, losses = losses + %s, draws = draws + %s, total_games = total_games + %s 
            WHERE telegram_id = %s
        """
        cursor.execute(adapt_query(upd_q), (new_score, new_rank, w_inc, l_inc, d_inc, g_inc, telegram_id))
        conn.commit()
        
        # Purge caching dependencies instantly to guarantee atomicity view synchronization
        global_cache.invalidate(["users_top_players", "system_top_10_ids"])
        
        log_audit_event("stats_mutation", telegram_id, telegram_id, {
            "score_delta": score_change,
            "old_score": current_score,
            "new_score": new_score,
            "old_rank": user.get('rank'),
            "new_rank": new_rank,
            "match_result": match_result
        })
            
        return {
            "rank_changed": rank_changed,
            "new_rank": new_rank,
            "score": new_score
        }
    except Exception as e:
        logger.error(f"Error inside update_stats transactional sequence: {e} | Trace:\n{traceback.format_exc()}")
        if conn:
            conn.rollback()
        return None
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if not is_pg:
            _sqlite_thread_lock.release()
        release_db_connection(conn, is_pg)

def get_top_players() -> List[Dict[str, Any]]:
    cache_key = "users_top_players"
    cached_val = global_cache.get(cache_key)
    if cached_val is not None:
        return cached_val

    rows = execute_read_all("SELECT * FROM users ORDER BY score DESC, total_games DESC LIMIT 10")
    if not rows:
        return []
    top_10_ids = [int(r['telegram_id']) for r in rows]
    formatted = []
    for r in rows:
        ud = dict(r)
        
        if IS_POSTGRES:
            if 'unlocked_titles' in ud and not isinstance(ud['unlocked_titles'], str) and ud['unlocked_titles'] is not None:
                ud['unlocked_titles'] = json.dumps(ud['unlocked_titles'], ensure_ascii=False)
            elif 'unlocked_titles' in ud and ud['unlocked_titles'] is None:
                ud['unlocked_titles'] = '[]'
                
            if 'unlocked_perks' in ud and not isinstance(ud['unlocked_perks'], str) and ud['unlocked_perks'] is not None:
                ud['unlocked_perks'] = json.dumps(ud['unlocked_perks'], ensure_ascii=False)
            elif 'unlocked_perks' in ud and ud['unlocked_perks'] is None:
                ud['unlocked_perks'] = '[]'
        else:
            ud['unlocked_titles'] = json.dumps(safe_json_deserialize(ud.get('unlocked_titles')), ensure_ascii=False)
            ud['unlocked_perks'] = json.dumps(safe_json_deserialize(ud.get('unlocked_perks')), ensure_ascii=False)
                
        if int(ud['telegram_id']) in top_10_ids:
            ud['title'] = "GOD OF DICE"
        formatted.append(ud)
        
    global_cache.set(cache_key, formatted, ttl=15.0)
    return formatted

def log_score_source(telegram_id: int, game_type: str) -> None:
    # Explicit query parameter validation checks
    if not str(game_type).strip():
        return
    execute_write("""
        INSERT INTO score_logs (telegram_id, game_type, count) VALUES (%s, %s, 1)
        ON CONFLICT (telegram_id, game_type) DO UPDATE SET count = score_logs.count + 1
    """, (telegram_id, game_type))

def get_current_active_event() -> Optional[Dict[str, Any]]:
    cache_key = "system_active_event"
    cached_val = global_cache.get(cache_key)
    if cached_val is not None:
        return cached_val

    ev_raw = execute_read_one("SELECT * FROM active_event ORDER BY id DESC LIMIT 1")
    if not ev_raw:
        return None
    ev = dict(ev_raw)
    try:
        time_str = ev['end_time'].strip()
        fmt = "%Y-%m-%d %H:%M" if len(time_str) == 16 else "%Y-%m-%d %H:%M:%S"
        if datetime.now() > datetime.strptime(time_str, fmt):
            execute_write("DELETE FROM active_event WHERE id = %s", (ev['id'],))
            global_cache.invalidate(["system_active_event"])
            log_audit_event("event_expiration_cleanup", None, ev.get("id"), {"event_name": ev.get("event_name")})
            return None
            
        global_cache.set(cache_key, ev, ttl=30.0)
        return ev
    except Exception as e:
        logger.error(f"Error checking active event timeline parsing window: {e}")
        return None

def get_infinity_ranks() -> List[Dict[str, Any]]:
    return execute_read_all("SELECT * FROM infinity_rank ORDER BY score DESC;")

def smart_add_redeem_code(code: str, title_name: str, max_uses: int, duration_hours: int) -> str:
    final_code = code.strip()
    if final_code.lower() in ["رندم", "random"]:
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        final_code = f"RDM-{suffix}"
    
    validate_write_operation("redeem_codes", {
        "title_name": title_name,
        "max_uses": max_uses,
        "duration_hours": duration_hours
    })
    
    execute_write("""
        INSERT INTO redeem_codes (code, title_name, max_uses, current_uses, duration_hours)
        VALUES (%s, %s, %s, 0, %s) ON CONFLICT (code) DO UPDATE SET max_uses = %s, duration_hours = %s
    """, (final_code, title_name, max_uses, duration_hours, max_uses, duration_hours))
    
    log_audit_event("redeem_code_generation", None, final_code, {
        "title_reward": title_name,
        "max_uses": max_uses,
        "duration_hours": duration_hours
    })
    return final_code
