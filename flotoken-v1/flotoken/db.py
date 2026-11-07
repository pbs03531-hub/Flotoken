"""SQLite access, schema and settings."""
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner','cashier','kitchen')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL UNIQUE,                          -- 10-digit Indian mobile, digits only
    password_hash TEXT NOT NULL,
    phone_verified INTEGER NOT NULL DEFAULT 0,           -- 1 once OTP verification is added
    consent_at INTEGER NOT NULL,                         -- when they accepted the data notice
    created_at INTEGER NOT NULL,
    last_login_at INTEGER,
    login_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS menu (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    name TEXT NOT NULL,
    price INTEGER NOT NULL CHECK (price >= 0),          -- rupees
    diet TEXT NOT NULL DEFAULT '' CHECK (diet IN ('','veg','nonveg')),
    available INTEGER NOT NULL DEFAULT 1,               -- 0 = sold out for today
    active INTEGER NOT NULL DEFAULT 1,                  -- 0 = deleted (kept so old bills stay valid)
    sort_order INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    image BLOB,                                         -- small JPEG/PNG/WebP, compressed in the browser
    image_type TEXT NOT NULL DEFAULT '',
    image_v INTEGER NOT NULL DEFAULT 0                  -- changes whenever the photo changes (cache busting)
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,                                   -- IST date; tokens restart every day
    tok INTEGER NOT NULL,
    code TEXT NOT NULL UNIQUE,                           -- private tracking code for the customer link
    source TEXT NOT NULL CHECK (source IN ('counter','app')),
    status TEXT NOT NULL DEFAULT 'placed'
        CHECK (status IN ('placed','preparing','ready','collected','cancelled')),
    customer_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    eta_min INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    preparing_at INTEGER,
    ready_at INTEGER,
    collected_at INTEGER,
    cancelled_at INTEGER,
    cancel_reason TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    customer_id INTEGER REFERENCES customers(id),        -- NULL for old orders and deleted accounts
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    rating_note TEXT NOT NULL DEFAULT '',
    rated_at INTEGER,
    UNIQUE (day, tok)
);
CREATE TABLE IF NOT EXISTS order_items (
    order_id INTEGER NOT NULL REFERENCES orders(id),
    item_id INTEGER NOT NULL REFERENCES menu(id),
    name TEXT NOT NULL,                                  -- copied at order time so later menu
    price INTEGER NOT NULL,                              -- edits never change an old bill
    qty INTEGER NOT NULL CHECK (qty > 0),
    PRIMARY KEY (order_id, item_id)
);
CREATE TABLE IF NOT EXISTS payments (                    -- refunds are negative amounts
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    method TEXT NOT NULL CHECK (method IN ('UPI','Cash')),
    amount INTEGER NOT NULL,
    at INTEGER NOT NULL,
    user_id INTEGER REFERENCES users(id),                -- staff who recorded it (NULL = system)
    ref TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS order_log (                   -- audit trail: who changed what, when
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    text TEXT NOT NULL,
    at INTEGER NOT NULL,
    user TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_orders_day ON orders(day, status);
CREATE INDEX IF NOT EXISTS idx_orders_phone ON orders(phone);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);
"""

# Created after migrations, because old databases only get these columns then.
LATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
"""

DEFAULT_SETTINGS = {
    "restaurant_name": "My Restaurant",
    "accepting_orders": "1",          # 1 = phone orders open
    "payment_mode": "demo",           # demo | upi_manual
    "upi_vpa": "",
    "upi_name": "",
    "eta_base": "10",                 # minutes
    "eta_per_order": "4",             # extra minutes per order already waiting
    "whatsapp_template": "Hi {name}, your order at {restaurant} is ready. Token {tok}. Please collect it at the parcel counter.",
    "receipt_address": "",
    "receipt_phone": "",
    "receipt_footer": "Thank you! Visit again.",
}

# Settings that customers (not logged in) may see.
PUBLIC_SETTINGS = ("restaurant_name", "accepting_orders", "payment_mode")


def db():
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DB_FILE"], timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


# Columns added after the first release. Older databases get them automatically at start-up.
MIGRATIONS = {
    "menu": [
        ("description", "TEXT NOT NULL DEFAULT ''"),
        ("image", "BLOB"),
        ("image_type", "TEXT NOT NULL DEFAULT ''"),
        ("image_v", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "orders": [
        ("customer_id", "INTEGER REFERENCES customers(id)"),
        ("rating", "INTEGER CHECK (rating BETWEEN 1 AND 5)"),
        ("rating_note", "TEXT NOT NULL DEFAULT ''"),
        ("rated_at", "INTEGER"),
    ],
}


def init_db(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")   # readers do not block the writer
    conn.executescript(SCHEMA)
    for table, columns in MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    conn.executescript(LATE_INDEXES)
    conn.commit()
    conn.close()


def all_settings():
    saved = {r["key"]: r["value"] for r in db().execute("SELECT key, value FROM settings")}
    return {**DEFAULT_SETTINGS, **saved}


def public_settings():
    s = all_settings()
    return {k: s[k] for k in PUBLIC_SETTINGS}


def set_setting(key, value):
    db().execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))


SAMPLE_MENU = {
    "Biryani": [("Mutton Biryani", 280, "nonveg"), ("Chicken Biryani", 220, "nonveg"), ("Egg Biryani", 160, "nonveg")],
    "Starters": [("Pepper Chicken Dry", 210, "nonveg"), ("Mutton Chops", 260, "nonveg"), ("Egg Fry", 40, "nonveg")],
    "Meals & Tiffin": [("Mudde & Naati Saaru", 150, "nonveg"), ("Kal Dosa (2)", 60, "veg"), ("Curd Rice", 70, "veg")],
}


def seed_sample_menu():
    d = db()
    for i, (cat, items) in enumerate(SAMPLE_MENU.items()):
        cid = d.execute("INSERT INTO categories (name, sort_order) VALUES (?, ?)", (cat, i)).lastrowid
        for j, (name, price, diet) in enumerate(items):
            d.execute("INSERT INTO menu (category_id, name, price, diet, sort_order) VALUES (?,?,?,?,?)",
                      (cid, name, price, diet, j))
