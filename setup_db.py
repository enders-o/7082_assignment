"""Initialize demo data in a chosen local SQLite file."""
import sqlite3
import sys

SCHEMA = '''
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price REAL NOT NULL CHECK (price >= 0),
    stock INTEGER NOT NULL CHECK (stock >= 0)
);
CREATE TABLE IF NOT EXISTS saved_cart (
    user_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (user_id, sku)
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    amount REAL,
    status TEXT,
    request_id TEXT
);
-- One order per request id: makes repeated/duplicate checkout requests idempotent.
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_request_id ON orders(request_id);
'''


def initialize(db_path='shop.db'):
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.executescript(SCHEMA)
            conn.executemany('INSERT OR IGNORE INTO products VALUES (?, ?, ?, ?)', [
                ('LAP-01', 'Laptop', 999.99, 5),
                ('MOU-01', 'Wireless mouse', 29.95, 20),
                ('USB-01', 'USB cable', 9.99, 50),
            ])
    finally:
        conn.close()


if __name__ == '__main__':
    initialize(sys.argv[1] if len(sys.argv) > 1 else 'shop.db')
