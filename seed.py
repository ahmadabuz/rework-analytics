# seed.py
import random
from datetime import datetime, timedelta
from db import init_db, get_conn, append_event

random.seed(42)

TIERS = ["free", "paid", "enterprise"]
CATEGORIES = ["billing", "technical", "cancellation", "complaint"]
SUBJECTS = {
    "billing": ["Wrong charge on invoice", "Double payment", "Refund not received", "Subscription renewal error"],
    "technical": ["App crashes on login", "Cannot connect to service", "Error 500 on checkout", "Password reset loop"],
    "cancellation": ["Cancel my subscription", "Want to close account", "Stop auto-renewal"],
    "complaint": ["Rude support agent", "Wait time too long", "Service outage complaint"],
}


def seed():
    init_db()
    conn = get_conn()
    conn.execute("DELETE FROM ticket_events")
    conn.execute("DELETE FROM tickets")
    conn.execute("DELETE FROM customers")
    conn.execute("DELETE FROM agents")

    agents = ["Ahmed", "Sara", "Fatima", "Omar"]

    for name in agents:
        conn.execute("INSERT INTO agents (name) VALUES (?)", (name,))

    for i in range(20):
        tier = random.choice(TIERS)
        conn.execute("INSERT INTO customers (name, phone, tier) VALUES (?,?,?)",
                     (f"Customer {i}", f"555{i:04d}", tier))

    conn.commit()

    now = datetime.utcnow()
    for i in range(30):
        cat = random.choice(CATEGORIES)
        subj = random.choice(SUBJECTS[cat])
        cust = random.randint(1, 20)
        agent = random.randint(1, 4)

        # Create a random starting date in the past
        created = now - timedelta(days=random.randint(5, 20), hours=random.randint(0, 12))

        cur = conn.execute("""
            INSERT INTO tickets (customer_id, subject, description, category, assigned_agent_id, created_at)
            VALUES (?,?,?,?,?,?)
        """, (cust, subj, f"Customer reported: {subj}.", cat, agent, created.isoformat()))
        ticket_id = cur.lastrowid
        conn.commit()

        # Insert 'created' event with the correct past timestamp
        conn.execute("INSERT INTO ticket_events (ticket_id, event_type, actor, note, created_at) VALUES (?,?,?,?,?)",
                     (ticket_id, "created", "Customer", "Ticket created", created.isoformat()))
        conn.commit()

        # 60% get resolved once
        if random.random() < 0.6:
            resolved_at = created + timedelta(hours=random.randint(1, 48))
            # FIXED: Using agents[agent - 1] to grab the actual name
            conn.execute(
                "INSERT INTO ticket_events (ticket_id, event_type, actor, note, created_at) VALUES (?,?,?,?,?)",
                (ticket_id, "resolved", agents[agent - 1], "First resolution attempt", resolved_at.isoformat()))
            conn.commit()

            # 30% of resolved get reopened 1-3 times
            if random.random() < 0.3:
                for r in range(random.randint(1, 3)):
                    reopen_at = resolved_at + timedelta(hours=random.randint(1, 72))
                    conn.execute(
                        "INSERT INTO ticket_events (ticket_id, event_type, actor, note, created_at) VALUES (?,?,?,?,?)",
                        (ticket_id, "reopened", "Customer", "Issue came back", reopen_at.isoformat()))
                    conn.commit()
                    # sometimes re-resolved
                    if random.random() < 0.5:
                        re_res_at = reopen_at + timedelta(hours=random.randint(1, 24))
                        # FIXED: Using agents[agent - 1] to grab the actual name
                        conn.execute(
                            "INSERT INTO ticket_events (ticket_id, event_type, actor, note, created_at) VALUES (?,?,?,?,?)",
                            (ticket_id, "resolved", agents[agent - 1], "Second attempt", re_res_at.isoformat()))
                        conn.commit()
                        resolved_at = re_res_at

    conn.close()
    print("Seeded: 20 customers, 4 agents, 30 tickets with rework history.")

if __name__ == "__main__":
    seed()