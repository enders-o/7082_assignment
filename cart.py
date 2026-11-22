"""Shopping cart and discount logic.

Money is calculated in integer cents internally to avoid binary floating-point
errors, and the discounted total is always derived from the *current* lines, so
editing the cart after applying a coupon can never leave a stale price.
"""
import logging

from models import CartLine

log = logging.getLogger(__name__)

# code -> function(subtotal_cents) -> discounted cents
DISCOUNTS = {
    'WELCOME10': lambda cents: (cents * 90 + 50) // 100,   # 10% off, rounded half-up
    'STUDENT20': lambda cents: (cents * 80 + 50) // 100,   # 20% off, rounded half-up
    'SAVE15': lambda cents: max(0, cents - 1500),          # 15.00 off, never below zero
    'FREESHIP': lambda cents: cents,                       # no shipping in this model: price unchanged
}


def _cents(amount):
    return int(round(amount * 100))


def _valid_quantity(quantity):
    return isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0


class ShoppingCart:
    def __init__(self, user_id, repository):
        self.user_id = user_id
        self.repository = repository
        self.lines = []
        self.discount_code = None

    def add_item(self, sku, quantity):
        if not _valid_quantity(quantity):
            log.warning('Invalid quantity: %r', quantity)
            return False
        product = self.repository.get_product(sku)
        if not product:
            log.warning('Unknown product: %r', sku)
            return False
        existing = next((x for x in self.lines if x.sku == sku), None)
        wanted = quantity + (existing.quantity if existing else 0)
        # Compare against the TOTAL wanted, not just this call's quantity.
        if product.stock < wanted:
            log.warning('Not enough stock for %s', sku)
            return False
        if existing:
            existing.quantity = wanted
        else:
            self.lines.append(CartLine(sku, product.name, product.price, quantity))
        return True

    def remove_item(self, sku, quantity=None):
        if quantity is not None and not _valid_quantity(quantity):
            log.warning('Invalid quantity: %r', quantity)
            return False
        line = next((x for x in self.lines if x.sku == sku), None)
        if line is None:
            log.warning('Item not found: %r', sku)
            return False
        if quantity is None or quantity >= line.quantity:
            self.lines.remove(line)
        else:
            line.quantity -= quantity
        return True

    def _subtotal_cents(self):
        return sum(_cents(line.unit_price) * line.quantity for line in self.lines)

    def subtotal(self):
        return self._subtotal_cents() / 100

    def total(self):
        cents = self._subtotal_cents()
        if self.discount_code is not None:
            cents = DISCOUNTS[self.discount_code](cents)
        return cents / 100

    def apply_discount(self, code):
        """Set the active coupon. Coupons replace each other; they never stack."""
        if code not in DISCOUNTS:
            log.warning('Invalid coupon: %r', code)
            return False
        self.discount_code = code
        return True

    def remove_discount(self):
        self.discount_code = None

    def load(self):
        """Replace the cart contents with the saved cart (safe to call repeatedly)."""
        self.lines = []
        for sku, quantity in self.repository.get_saved_cart(self.user_id):
            self.add_item(sku, quantity)

    def save(self):
        self.repository.save_cart(self.user_id, self.lines)
