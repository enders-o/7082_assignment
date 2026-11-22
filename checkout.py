"""Checkout coordinator.

Flow (each step protects against a specific failure):
1. validate input                      -> no work for bad requests
2. look up request_id                  -> repeated requests are idempotent (no double charge)
3. claim request_id with a 'pending' order (unique index) -> concurrent duplicates lose the race
4. atomically reserve stock            -> never oversell; nothing changes if any line is short
5. charge the payment gateway
6. paid  -> mark order paid, clear cart
   other -> release the reserved stock, record the failure, KEEP the cart so the user can retry
"""
import logging
import sqlite3

from models import OrderResult

log = logging.getLogger(__name__)


class CheckoutService:
    def __init__(self, repository, payment_gateway):
        self.repository = repository
        self.payment_gateway = payment_gateway

    def _existing_result(self, cart, request_id):
        row = self.repository.get_order_by_request_id(request_id)
        if row is None:
            return None
        order_id, user_id, amount, status = row
        if user_id != cart.user_id:
            # A request id may not be reused by a different user.
            return OrderResult(None, 'duplicate_request', 0)
        return OrderResult(order_id, status, amount)

    def checkout(self, cart, payment_token, request_id):
        if len(cart.lines) == 0:
            return OrderResult(None, 'empty', 0)
        if not request_id:
            return OrderResult(None, 'missing_request_id', 0)
        if not payment_token:
            return OrderResult(None, 'invalid_payment', 0)

        existing = self._existing_result(cart, request_id)
        if existing is not None:
            return existing

        amount = cart.total()
        try:
            order_id = self.repository.save_order(cart.user_id, amount, 'pending', request_id)
        except sqlite3.IntegrityError:
            # Another request with the same id won the race.
            return self._existing_result(cart, request_id) or OrderResult(None, 'duplicate_request', 0)

        lines = list(cart.lines)
        if not self.repository.reserve_stock(lines):
            self.repository.update_order_status(order_id, 'out_of_stock')
            return OrderResult(order_id, 'out_of_stock', amount)

        # Never log the payment token (sensitive data).
        try:
            response = self.payment_gateway.charge(amount, payment_token)
            status = 'paid' if response['approved'] else 'declined'
        except Exception:
            log.exception('Payment gateway error for order %s', order_id)
            status = 'payment_error'

        if status != 'paid':
            self.repository.release_stock(lines)
        self.repository.update_order_status(order_id, status)

        if status == 'paid':
            cart.lines.clear()
            cart.discount_code = None
            cart.save()
        return OrderResult(order_id, status, amount)
