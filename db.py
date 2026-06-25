import os
import shutil
import sqlite3
import json
from datetime import date, datetime
from pathlib import Path

# DB location is configurable via MENTOR_DB_PATH (defaults to data/mentor.db).
# Useful for pointing throwaway runs (or future tests) at a temp file
# so the real database is never touched.
DB_PATH = Path(os.getenv("MENTOR_DB_PATH", "data/mentor.db"))

# Rolling backups: one snapshot file per day, keep the most recent N days.
BACKUP_DIR = DB_PATH.parent / "backups"
BACKUP_KEEP = 7

# Single source of truth for the skill tree. Add a domain here and it is
# back-filled for every user on their next login (see get_or_create_user).
DOMAINS = [
    "SQL", "Python", "Spark", "Airflow", "Kafka", "Databricks",
    "Iceberg", "Delta Lake", "Snowflake", "dbt", "ETL / ELT",
    "Stream Processing", "Data Quality", "Data Modeling", "Data Governance",
    "System Design", "AWS", "Terraform / IaC", "Linux", "Bash",
    "Docker", "Kubernetes", "Git", "CI/CD", "Monitoring", "Observability",
]


def get_conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        created_at TEXT DEFAULT (date('now'))
    );

    CREATE TABLE IF NOT EXISTS skill_levels (
        user_id INTEGER,
        domain TEXT,
        level INTEGER DEFAULT 1,
        xp INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, domain),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        date TEXT,
        domain TEXT,
        challenge_id TEXT,
        challenge_title TEXT,
        challenge_text TEXT,
        challenge_json TEXT,
        messages TEXT DEFAULT '[]',
        assessment TEXT,
        score INTEGER,
        completed INTEGER DEFAULT 0,
        started_at TEXT DEFAULT (datetime('now')),
        completed_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS streaks (
        user_id INTEGER PRIMARY KEY,
        current_streak INTEGER DEFAULT 0,
        longest_streak INTEGER DEFAULT 0,
        last_active_date TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        achievement_key TEXT,
        unlocked_at TEXT DEFAULT (datetime('now')),
        UNIQUE(user_id, achievement_key),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)

    # Add challenge_json to DBs created before it existed (CREATE TABLE IF NOT
    # EXISTS won't alter an existing table). Storing the full challenge as JSON lets
    # a resumed session rehydrate fully, which the flat columns can't.
    cols = {r["name"] for r in c.execute("PRAGMA table_info(sessions)").fetchall()}
    if "challenge_json" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN challenge_json TEXT")

    conn.commit()
    conn.close()


def get_or_create_user(name: str) -> int:
    conn = get_conn()
    c = conn.cursor()
    row = c.execute("SELECT id FROM users WHERE name=?", (name,)).fetchone()
    if row:
        user_id = row["id"]
    else:
        c.execute("INSERT INTO users (name) VALUES (?)", (name,))
        user_id = c.lastrowid
        c.execute("INSERT OR IGNORE INTO streaks (user_id) VALUES (?)", (user_id,))
    # Back-fill skills for new AND existing users, so domains added to DOMAINS
    # later show up for everyone without a migration.
    c.executemany(
        "INSERT OR IGNORE INTO skill_levels (user_id, domain) VALUES (?, ?)",
        [(user_id, d) for d in DOMAINS]
    )
    conn.commit()
    conn.close()
    return user_id


def get_skill_levels(user_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT domain, level, xp FROM skill_levels WHERE user_id=? ORDER BY domain",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_skill(user_id: int, domain: str, xp_gain: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE skill_levels SET xp = xp + ? WHERE user_id=? AND domain=?",
        (xp_gain, user_id, domain)
    )
    # level up every 100 xp
    c.execute("""
        UPDATE skill_levels
        SET level = 1 + (xp / 100)
        WHERE user_id=? AND domain=?
    """, (user_id, domain))
    conn.commit()
    conn.close()


def get_streak(user_id: int) -> dict:
    conn = get_conn()
    row = conn.execute(
        "SELECT current_streak, longest_streak, last_active_date FROM streaks WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def update_streak(user_id: int):
    today = date.today().isoformat()
    conn = get_conn()
    c = conn.cursor()
    row = c.execute(
        "SELECT current_streak, longest_streak, last_active_date FROM streaks WHERE user_id=?",
        (user_id,)
    ).fetchone()
    if not row:
        conn.close()
        return

    last = row["last_active_date"]
    current = row["current_streak"]
    longest = row["longest_streak"]

    if last == today:
        conn.close()
        return

    from datetime import timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    if last == yesterday:
        current += 1
    else:
        current = 1

    longest = max(longest, current)
    c.execute(
        "UPDATE streaks SET current_streak=?, longest_streak=?, last_active_date=? WHERE user_id=?",
        (current, longest, today, user_id)
    )
    conn.commit()
    conn.close()


def backup_db():
    """Snapshot the DB to one file per day under <data>/backups/, keeping the most
    recent BACKUP_KEEP days. Called after every session write, so any session stays
    recoverable. Best-effort: a failed snapshot never breaks the app."""
    if not DB_PATH.exists():
        return
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB_PATH, BACKUP_DIR / f"mentor-{date.today().isoformat()}.db")
        snaps = sorted(BACKUP_DIR.glob("mentor-*.db"))  # ISO names sort by date
        for old in snaps[:-BACKUP_KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def save_session(user_id: int, domain: str, challenge: dict) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO sessions (user_id, date, domain, challenge_id, challenge_title, challenge_text, challenge_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        date.today().isoformat(),
        domain,
        challenge.get("id", ""),
        challenge.get("title", ""),
        challenge.get("text", ""),
        json.dumps(challenge),  # full dict, so key_concepts/hints/revisits survive a resume
    ))
    conn.commit()
    session_id = c.lastrowid
    conn.close()
    backup_db()  # snapshot: session started
    return session_id


def update_session_messages(session_id: int, messages: list):
    conn = get_conn()
    conn.execute(
        "UPDATE sessions SET messages=? WHERE id=?",
        (json.dumps(messages), session_id)
    )
    conn.commit()
    conn.close()
    backup_db()  # snapshot: progress / abandon-safe


def complete_session(session_id: int, assessment: str, score: int):
    conn = get_conn()
    conn.execute("""
        UPDATE sessions
        SET completed=1, assessment=?, score=?, completed_at=datetime('now')
        WHERE id=?
    """, (assessment, score, session_id))
    conn.commit()
    conn.close()
    backup_db()  # snapshot: session finished


def get_today_session(user_id: int) -> dict | None:
    today = date.today().isoformat()
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM sessions WHERE user_id=? AND date=? ORDER BY id DESC LIMIT 1",
        (user_id, today)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_recent_sessions(user_id: int, limit: int = 10) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_weak_spots(user_id: int, limit: int = 15, cap: int = 6) -> list[dict]:
    """De-duplicated recent 'next focus' topics for the Rematch picker, newest
    first. Each entry is {label, domain, date}."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT domain, assessment, date FROM sessions "
        "WHERE user_id=? AND completed=1 AND assessment IS NOT NULL "
        "ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()

    seen, out = set(), []
    for r in rows:
        try:
            a = json.loads(r["assessment"])
        except (json.JSONDecodeError, TypeError):
            continue
        label = (a.get("next_focus") or "").strip()
        key = label.lower()
        if not label or key in seen:
            continue
        seen.add(key)
        out.append({"label": label, "domain": r["domain"], "date": r["date"]})
        if len(out) >= cap:
            break
    return out


def grant_achievement(user_id: int, key: str) -> bool:
    """Returns True if newly unlocked."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO achievements (user_id, achievement_key) VALUES (?, ?)",
            (user_id, key)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def get_achievements(user_id: int) -> list[str]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT achievement_key FROM achievements WHERE user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()
    return [r["achievement_key"] for r in rows]
