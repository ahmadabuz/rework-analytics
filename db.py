# db.py
import sqlite3
from datetime import datetime, timedelta
import random

DB_PATH = "ticketing.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT,
        tier TEXT NOT NULL CHECK (tier IN ('free','paid','enterprise'))
    );

    CREATE TABLE IF NOT EXISTS agents (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL REFERENCES customers(id),
        subject TEXT NOT NULL,
        description TEXT,
        category TEXT NOT NULL CHECK (category IN ('billing','technical','cancellation','complaint')),
        assigned_agent_id INTEGER REFERENCES agents(id),
        created_at TEXT NOT NULL,
        resolved_at TEXT
    );

    CREATE TABLE IF NOT EXISTS ticket_events (
        id INTEGER PRIMARY KEY,
        ticket_id INTEGER NOT NULL REFERENCES tickets(id),
        event_type TEXT NOT NULL CHECK (event_type IN
            ('created','assigned','commented','reopened','resolved','closed')),
        actor TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_events_ticket ON ticket_events(ticket_id);
    """)
    conn.commit()
    conn.close()


# ---------- DERIVED QUERIES (the portfolio story) ----------

def get_agent_queue(agent_id):
    """
    Open tickets assigned to this agent, sorted by rework first, then age.
    Reopen count is DERIVED from the event log, never stored.
    """
    conn = get_conn()
    rows = conn.execute("""
        WITH reopen_counts AS (
            SELECT ticket_id, COUNT(*) AS reopen_count
            FROM ticket_events
            WHERE event_type = 'reopened'
            GROUP BY ticket_id
        ),
        latest_status AS (
            SELECT ticket_id, event_type AS status
            FROM ticket_events e1
            WHERE created_at = (
                SELECT MAX(created_at) FROM ticket_events e2
                WHERE e2.ticket_id = e1.ticket_id
                  AND e2.event_type IN ('resolved','closed','reopened','created')
            )
        )
        SELECT
            t.id,
            t.subject,
            t.category,
            t.created_at,
            c.name AS customer_name,
            c.tier,
            COALESCE(rc.reopen_count, 0) AS reopen_count
        FROM tickets t
        JOIN customers c ON c.id = t.customer_id
        JOIN latest_status ls ON ls.ticket_id = t.id
        LEFT JOIN reopen_counts rc ON rc.ticket_id = t.id
        WHERE t.assigned_agent_id = ?
          AND ls.status NOT IN ('resolved','closed')
        ORDER BY reopen_count DESC, t.created_at ASC
    """, (agent_id,)).fetchall()
    conn.close()
    return rows


def get_ticket_with_events(ticket_id):
    conn = get_conn()
    ticket = conn.execute("""
        SELECT t.*, c.name AS customer_name, c.tier, c.phone,
               a.name AS agent_name
        FROM tickets t
        JOIN customers c ON c.id = t.customer_id
        LEFT JOIN agents a ON a.id = t.assigned_agent_id
        WHERE t.id = ?
    """, (ticket_id,)).fetchone()
    events = conn.execute("""
        SELECT * FROM ticket_events
        WHERE ticket_id = ?
        ORDER BY created_at ASC
    """, (ticket_id,)).fetchall()
    conn.close()
    return ticket, events


def get_supervisor_dashboard():
    conn = get_conn()
    # Rework rate per agent: resolved tickets that had >=1 reopen before resolution
    agent_rework = conn.execute("""
        WITH resolved AS (
            SELECT t.id, t.assigned_agent_id
            FROM tickets t
            JOIN ticket_events e ON e.ticket_id = t.id
            WHERE e.event_type = 'resolved'
        ),
        reworked AS (
            SELECT DISTINCT ticket_id
            FROM ticket_events
            WHERE event_type = 'reopened'
        )
        SELECT
            a.name AS agent_name,
            COUNT(DISTINCT r.id) AS resolved_count,
            COUNT(DISTINCT CASE WHEN rw.ticket_id IS NOT NULL THEN r.id END) AS reworked_count
        FROM resolved r
        JOIN agents a ON a.id = r.assigned_agent_id
        LEFT JOIN reworked rw ON rw.ticket_id = r.id
        GROUP BY a.id
        ORDER BY reworked_count DESC
    """).fetchall()

    # Rework rate per category
    category_rework = conn.execute("""
        WITH reworked AS (
            SELECT DISTINCT ticket_id FROM ticket_events WHERE event_type = 'reopened'
        )
        SELECT
            t.category,
            COUNT(*) AS total,
            COUNT(CASE WHEN rw.ticket_id IS NOT NULL THEN 1 END) AS reworked
        FROM tickets t
        LEFT JOIN reworked rw ON rw.ticket_id = t.id
        GROUP BY t.category
        ORDER BY reworked DESC
    """).fetchall()

    # The chronic pile: open tickets reopened 2+
    chronic = conn.execute("""
        WITH reopen_counts AS (
            SELECT ticket_id, COUNT(*) AS n
            FROM ticket_events WHERE event_type = 'reopened'
            GROUP BY ticket_id HAVING n >= 2
        ),
        open_tickets AS (
            SELECT t.id FROM tickets t
            WHERE (SELECT event_type FROM ticket_events
                   WHERE ticket_id = t.id
                   AND event_type IN ('resolved','closed','reopened')
                   ORDER BY created_at DESC LIMIT 1)
                  NOT IN ('resolved','closed')
        )
        SELECT t.id, t.subject, t.category, rc.n AS reopen_count, c.tier
        FROM tickets t
        JOIN reopen_counts rc ON rc.ticket_id = t.id
        JOIN customers c ON c.id = t.customer_id
        WHERE t.id IN (SELECT id FROM open_tickets)
        ORDER BY rc.n DESC
    """).fetchall()
    conn.close()
    return agent_rework, category_rework, chronic


# ---------- EVENT APPEND HELPERS ----------

def append_event(ticket_id, event_type, actor_id, note=None):
    """Every action goes through here. Never UPDATE tickets — append only."""
    conn = get_conn()

    # Look up the agent's real name
    agent = conn.execute("SELECT name FROM agents WHERE id = ?", (actor_id,)).fetchone()
    actor_name = agent["name"] if agent else f"Agent {actor_id}"

    conn.execute("""
        INSERT INTO ticket_events (ticket_id, event_type, actor, note, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (ticket_id, event_type, actor_name, note, datetime.utcnow().isoformat()))

    if event_type in ("resolved", "closed"):
        conn.execute("UPDATE tickets SET resolved_at = ? WHERE id = ?",
                     (datetime.utcnow().isoformat(), ticket_id))
    conn.commit()
    conn.close()