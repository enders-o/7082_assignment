"""SQLite persistence.

All SQL uses bound parameters (no string building), every connection is closed
even when an error occurs, and multi-statement operations run in one
transaction so they either fully succeed or fully roll back.
"""
import sqlite3
from contextlib import contextmanager

from models import Product


class StoreRepository:
    def __init__(self, db_path='shop.db'):
        self.db_path = db_path

    def connect(self):
        return sqlite3.connect(self.db_path, timeout=2)

    @contextmanager
    def _transaction(self):
        """Commit on success, roll back on error, always close the connection."""
        conn = self.connect()
        try:
            with conn:  # commits or rolls back
                yield conn
        finally:
            conn.close()

    # -- products ---------------------------------------------------------
    def get_product(self, sku):
        with self._transaction() as conn:
            row = conn.execute(
                'SELECT sku, name, price, stock FROM products WHERE sku = ?', (sku,)
            ).fetchone()
        return Product(*row) if row else None

    # -- saved carts ------------------------------------------------------
    def get_saved_cart(self, user_id):
        with self._transaction() as conn:
            return conn.execute(
                'SELECT sku, quantity FROM saved_cart WHERE user_id = ?', (user_id,)
            ).fetchall()

    def save_cart(self, user_id, lines):
        with self._transaction() as conn:
            conn.execute('DELETE FROM saved_cart WHERE user_id = ?', (user_id,))
            for line in lines:
                conn.execute(
                    'INSERT INTO saved_cart (user_id, sku, quantity) VALUES (?, ?, ?)',
                    (user_id, line.sku, line.quantity),
                )

    # -- inventory --------------------------------------------------------
    def reserve_stock(self, lines):
        """Atomically decrement stock for every line.

        Returns False (and changes nothing) if any product lacks enough stock.
        The ``stock >= ?`` guard makes the check and the update a single
        statement, so two concurrent checkouts cannot oversell.
        """
        conn = self.connect()
        try:
            for line in lines:
                cur = conn.execute(
                    'UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?',
                    (line.quantity, line.sku, line.quantity),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    return False
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def release_stock(self, lines):
        """Return previously reserved stock (payment declined / failed)."""
        with self._transaction() as conn:
            for line in lines:
                conn.execute(
                    'UPDATE products SET stock = stock + ? WHERE sku = ?',
                    (line.quantity, line.sku),
                )

    # -- orders -----------------------------------------------------------
    def save_order(self, user_id, amount, status, request_id):
        """Insert an order. Raises sqlite3.IntegrityError on a duplicate request_id."""
        with self._transaction() as conn:
            cur = conn.execute(
                'INSERT INTO orders(user_id, amount, status, request_id) VALUES (?, ?, ?, ?)',
                (user_id, amount, status, request_id),
            )
            return cur.lastrowid

    def update_order_status(self, order_id, status):
        with self._transaction() as conn:
            conn.execute('UPDATE orders SET status = ? WHERE id = ?', (status, order_id))

    def get_order_by_request_id(self, request_id):
        with self._transaction() as conn:
            return conn.execute(
                'SELECT id, user_id, amount, status FROM orders WHERE request_id = ?',
                (request_id,),
            ).fetchone()

    def list_orders(self, user_id):
        with self._transaction() as conn:
            return conn.execute(
                'SELECT id, user_id, amount, status FROM orders WHERE user_id = ? ORDER BY id DESC',
                (user_id,),
            ).fetchall()
