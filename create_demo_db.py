"""
create_demo_db.py — Generate demo_warehouse.db for Atlas.

Builds a small, realistic SQLite warehouse that ships with the project so the
Database Auto-Discovery Scanner has something to scan out of the box. The data
is coherent: customer ids match across stripe tables, subscription ids line up
with invoices, and the analytics_mrr_by_segment table mirrors a downstream
rollup of the source data.

Run: python create_demo_db.py
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "demo_warehouse.db")

SCHEMA = """
CREATE TABLE stripe_customers (
    id INTEGER PRIMARY KEY,
    email TEXT,
    customer_segment TEXT,
    name TEXT,
    created_at TEXT,
    is_active INTEGER
);

CREATE TABLE stripe_subscriptions (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER,
    plan_name TEXT,
    status TEXT,
    mrr REAL,
    started_at TEXT,
    FOREIGN KEY (customer_id) REFERENCES stripe_customers(id)
);

CREATE TABLE stripe_invoices (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER,
    subscription_id INTEGER,
    amount REAL,
    status TEXT,
    created_at TEXT,
    FOREIGN KEY (customer_id) REFERENCES stripe_customers(id),
    FOREIGN KEY (subscription_id) REFERENCES stripe_subscriptions(id)
);

CREATE TABLE hubspot_deals (
    deal_id INTEGER PRIMARY KEY,
    company_name TEXT,
    amount REAL,
    deal_stage TEXT,
    lead_source TEXT,
    owner_email TEXT
);

CREATE TABLE hubspot_contacts (
    contact_id INTEGER PRIMARY KEY,
    email TEXT,
    first_name TEXT,
    last_name TEXT,
    lifecycle_stage TEXT
);

CREATE TABLE analytics_mrr_by_segment (
    id INTEGER PRIMARY KEY,
    month TEXT,
    segment TEXT,
    total_mrr REAL,
    customer_count INTEGER
);
"""

# --- Seed data ------------------------------------------------------------

CUSTOMERS = [
    (1,  "alice@acme.io",       "enterprise", "Alice Tan",       "2024-01-15", 1),
    (2,  "bob@globex.com",      "smb",        "Bob Reyes",       "2024-02-03", 1),
    (3,  "carol@initech.com",   "enterprise", "Carol Nwosu",     "2024-02-20", 1),
    (4,  "dan@umbrella.co",     "startup",    "Dan Okafor",      "2024-03-11", 0),
    (5,  "erin@hooli.com",      "smb",        "Erin Castillo",   "2024-03-29", 1),
    (6,  "frank@piedpiper.com", "startup",    "Frank Mensah",    "2024-04-08", 1),
    (7,  "grace@stark.com",     "enterprise", "Grace Adeyemi",   "2024-04-22", 1),
    (8,  "henry@wayne.com",     "smb",        "Henry Park",      "2024-05-05", 0),
    (9,  "ivy@oscorp.com",      "startup",    "Ivy Bello",       "2024-05-19", 1),
    (10, "jack@cyberdyne.com",  "enterprise", "Jack Owusu",      "2024-06-01", 1),
    (11, "kate@aperture.com",   "smb",        "Kate Lawson",     "2024-06-14", 1),
    (12, "leo@tyrell.com",      "startup",    "Leo Diallo",      "2024-06-30", 1),
]

# (id, customer_id, plan_name, status, mrr, started_at)
SUBSCRIPTIONS = [
    (1,  1,  "Enterprise Annual", "active",   2000.0, "2024-01-16"),
    (2,  2,  "Growth Monthly",    "active",   299.0,  "2024-02-04"),
    (3,  3,  "Enterprise Annual", "active",   2500.0, "2024-02-21"),
    (4,  4,  "Starter Monthly",   "canceled", 49.0,   "2024-03-12"),
    (5,  5,  "Growth Monthly",    "active",   299.0,  "2024-03-30"),
    (6,  6,  "Starter Monthly",   "active",   49.0,   "2024-04-09"),
    (7,  7,  "Enterprise Annual", "active",   3000.0, "2024-04-23"),
    (8,  8,  "Growth Monthly",    "past_due", 299.0,  "2024-05-06"),
    (9,  9,  "Starter Monthly",   "active",   49.0,   "2024-05-20"),
    (10, 10, "Enterprise Annual", "active",   2200.0, "2024-06-02"),
    (11, 11, "Growth Monthly",    "active",   299.0,  "2024-06-15"),
    (12, 12, "Starter Monthly",   "active",   49.0,   "2024-07-01"),
]

# (id, customer_id, subscription_id, amount, status, created_at)
INVOICES = [
    (1,  1,  1,  2000.0, "paid",   "2024-01-16"),
    (2,  2,  2,  299.0,  "paid",   "2024-02-04"),
    (3,  3,  3,  2500.0, "paid",   "2024-02-21"),
    (4,  4,  4,  49.0,   "void",   "2024-03-12"),
    (5,  5,  5,  299.0,  "paid",   "2024-03-30"),
    (6,  6,  6,  49.0,   "paid",   "2024-04-09"),
    (7,  7,  7,  3000.0, "paid",   "2024-04-23"),
    (8,  8,  8,  299.0,  "open",   "2024-05-06"),
    (9,  9,  9,  49.0,   "paid",   "2024-05-20"),
    (10, 10, 10, 2200.0, "paid",   "2024-06-02"),
    (11, 11, 11, 299.0,  "paid",   "2024-06-15"),
    (12, 1,  1,  2000.0, "paid",   "2025-01-16"),
    (13, 3,  3,  2500.0, "paid",   "2025-02-21"),
    (14, 12, 12, 49.0,   "paid",   "2024-07-01"),
]

# (deal_id, company_name, amount, deal_stage, lead_source, owner_email)
DEALS = [
    (1,  "Acme Corp",       48000.0, "closed_won",   "referral",     "rep1@atlas.io"),
    (2,  "Globex",          3600.0,  "negotiation",  "inbound",      "rep2@atlas.io"),
    (3,  "Initech",         60000.0, "closed_won",   "outbound",     "rep1@atlas.io"),
    (4,  "Umbrella Co",     600.0,   "closed_lost",  "paid_ads",     "rep3@atlas.io"),
    (5,  "Hooli",           3600.0,  "proposal",     "inbound",      "rep2@atlas.io"),
    (6,  "Pied Piper",      600.0,   "qualified",    "event",        "rep3@atlas.io"),
    (7,  "Stark Industries",72000.0, "closed_won",   "referral",     "rep1@atlas.io"),
    (8,  "Wayne Enterprises",3600.0, "closed_lost",  "outbound",     "rep2@atlas.io"),
    (9,  "Oscorp",          600.0,   "qualified",    "paid_ads",     "rep3@atlas.io"),
    (10, "Cyberdyne",       52800.0, "negotiation",  "inbound",      "rep1@atlas.io"),
    (11, "Aperture Science",3600.0,  "proposal",     "event",        "rep2@atlas.io"),
    (12, "Tyrell Corp",     600.0,   "qualified",    "referral",     "rep3@atlas.io"),
]

# (contact_id, email, first_name, last_name, lifecycle_stage)
CONTACTS = [
    (1,  "alice@acme.io",       "Alice", "Tan",      "customer"),
    (2,  "bob@globex.com",      "Bob",   "Reyes",    "opportunity"),
    (3,  "carol@initech.com",   "Carol", "Nwosu",    "customer"),
    (4,  "dan@umbrella.co",     "Dan",   "Okafor",   "lead"),
    (5,  "erin@hooli.com",      "Erin",  "Castillo", "opportunity"),
    (6,  "frank@piedpiper.com", "Frank", "Mensah",   "lead"),
    (7,  "grace@stark.com",     "Grace", "Adeyemi",  "customer"),
    (8,  "henry@wayne.com",     "Henry", "Park",     "lead"),
    (9,  "ivy@oscorp.com",      "Ivy",   "Bello",    "lead"),
    (10, "jack@cyberdyne.com",  "Jack",  "Owusu",    "opportunity"),
    (11, "kate@aperture.com",   "Kate",  "Lawson",   "opportunity"),
    (12, "leo@tyrell.com",      "Leo",   "Diallo",   "lead"),
]

# (id, month, segment, total_mrr, customer_count) — downstream rollup.
MRR_BY_SEGMENT = [
    (1,  "2024-05", "enterprise", 7500.0, 3),
    (2,  "2024-05", "smb",        897.0,  3),
    (3,  "2024-05", "startup",    147.0,  3),
    (4,  "2024-06", "enterprise", 9700.0, 4),
    (5,  "2024-06", "smb",        897.0,  3),
    (6,  "2024-06", "startup",    147.0,  3),
    (7,  "2024-07", "enterprise", 9700.0, 4),
    (8,  "2024-07", "smb",        897.0,  3),
    (9,  "2024-07", "startup",    196.0,  4),
    (10, "2024-08", "enterprise", 9700.0, 4),
    (11, "2024-08", "smb",        897.0,  3),
    (12, "2024-08", "startup",    196.0,  4),
]


def main():
    # Recreate the database from scratch each run so it stays deterministic.
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript(SCHEMA)

    cursor.executemany("INSERT INTO stripe_customers VALUES (?,?,?,?,?,?)", CUSTOMERS)
    cursor.executemany("INSERT INTO stripe_subscriptions VALUES (?,?,?,?,?,?)", SUBSCRIPTIONS)
    cursor.executemany("INSERT INTO stripe_invoices VALUES (?,?,?,?,?,?)", INVOICES)
    cursor.executemany("INSERT INTO hubspot_deals VALUES (?,?,?,?,?,?)", DEALS)
    cursor.executemany("INSERT INTO hubspot_contacts VALUES (?,?,?,?,?)", CONTACTS)
    cursor.executemany("INSERT INTO analytics_mrr_by_segment VALUES (?,?,?,?,?)", MRR_BY_SEGMENT)

    conn.commit()
    conn.close()

    print(f"Created {DB_PATH}")
    print(
        f"  6 tables — {len(CUSTOMERS)} customers, {len(SUBSCRIPTIONS)} subscriptions, "
        f"{len(INVOICES)} invoices, {len(DEALS)} deals, {len(CONTACTS)} contacts, "
        f"{len(MRR_BY_SEGMENT)} analytics rows."
    )


if __name__ == "__main__":
    main()
