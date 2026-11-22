"""Unit tests for ShoppingCart (corrected behaviour)."""
import pytest

from cart import ShoppingCart
from repository import StoreRepository
from setup_db import initialize


@pytest.fixture
def repo(tmp_path):
    db = str(tmp_path / 'test.db')
    initialize(db)
    return StoreRepository(db)


@pytest.fixture
def cart(repo):
    return ShoppingCart('alice', repo)


@pytest.mark.parametrize('qty', [0, -1, -100, 1.5, '2', None, True])
def test_add_item_rejects_invalid_quantities(cart, qty):
    assert cart.add_item('USB-01', qty) is False
    assert cart.lines == []


def test_add_item_unknown_sku_rejected(cart):
    assert cart.add_item('NOPE', 1) is False
    assert cart.lines == []


def test_add_duplicate_product_merges_lines(cart):
    assert cart.add_item('USB-01', 2)
    assert cart.add_item('USB-01', 3)
    assert len(cart.lines) == 1
    assert cart.lines[0].quantity == 5


def test_stock_limit_counts_quantity_already_in_cart(cart):
    # LAP-01 has stock 5: 3 + 3 must be refused, cart stays at 3.
    assert cart.add_item('LAP-01', 3)
    assert cart.add_item('LAP-01', 3) is False
    assert cart.lines[0].quantity == 3


def test_add_exact_stock_boundary_allowed(cart):
    assert cart.add_item('LAP-01', 5)
    assert cart.add_item('LAP-01', 1) is False


def test_remove_partial_and_full(cart):
    cart.add_item('MOU-01', 5)
    assert cart.remove_item('MOU-01', 2)
    assert cart.lines[0].quantity == 3
    assert cart.remove_item('MOU-01', 3)  # quantity == remaining -> line removed
    assert cart.lines == []


def test_remove_without_quantity_removes_line(cart):
    cart.add_item('MOU-01', 5)
    assert cart.remove_item('MOU-01')
    assert cart.lines == []


@pytest.mark.parametrize('qty', [0, -3])
def test_remove_rejects_non_positive_quantity(cart, qty):
    cart.add_item('MOU-01', 2)
    assert cart.remove_item('MOU-01', qty) is False
    assert cart.lines[0].quantity == 2  # negative removal must not ADD items


def test_remove_missing_item_returns_false(cart):
    assert cart.remove_item('USB-01') is False


def test_subtotal_has_no_float_drift(cart):
    cart.add_item('MOU-01', 3)  # 3 * 29.95
    cart.add_item('USB-01', 3)  # 3 * 9.99
    assert cart.subtotal() == 119.82


@pytest.mark.parametrize('code,expected', [
    ('WELCOME10', 107.84),   # 119.82 * 0.9 = 107.838 -> 107.84
    ('STUDENT20', 95.86),    # 119.82 * 0.8 = 95.856  -> 95.86
    ('SAVE15', 104.82),
    ('FREESHIP', 119.82),
])
def test_discount_totals_rounded_to_cents(cart, code, expected):
    cart.add_item('MOU-01', 3)
    cart.add_item('USB-01', 3)
    assert cart.apply_discount(code)
    assert cart.total() == expected


def test_invalid_coupon_rejected_and_total_unchanged(cart):
    cart.add_item('USB-01', 1)
    assert cart.apply_discount('BOGUS') is False
    assert cart.total() == 9.99


def test_save15_never_makes_total_negative(cart):
    cart.add_item('USB-01', 1)  # 9.99 < 15
    cart.apply_discount('SAVE15')
    assert cart.total() == 0


def test_discounts_do_not_stack(cart):
    cart.add_item('MOU-01', 10)  # 299.50
    cart.apply_discount('WELCOME10')
    cart.apply_discount('WELCOME10')
    assert cart.total() == 269.55  # discounted once, not twice


def test_editing_cart_after_discount_recalculates_total(cart):
    cart.add_item('MOU-01', 10)           # 299.50
    cart.apply_discount('STUDENT20')
    assert cart.total() == 239.60
    cart.add_item('MOU-01', 5)            # 449.25 -> 359.40
    assert cart.total() == 359.40
    cart.remove_item('MOU-01', 10)        # 149.75 -> 119.80
    assert cart.total() == 119.80


def test_removing_everything_after_discount_gives_zero(cart):
    cart.add_item('USB-01', 1)
    cart.apply_discount('WELCOME10')
    cart.remove_item('USB-01')
    assert cart.total() == 0


def test_repeated_load_does_not_duplicate_quantities(repo):
    first = ShoppingCart('bob', repo)
    first.add_item('USB-01', 2)
    first.save()
    second = ShoppingCart('bob', repo)
    second.load()
    second.load()
    second.load()
    assert [(l.sku, l.quantity) for l in second.lines] == [('USB-01', 2)]


def test_saved_carts_are_isolated_per_user(repo):
    a = ShoppingCart('alice', repo)
    a.add_item('USB-01', 1)
    a.save()
    b = ShoppingCart('bob', repo)
    b.load()
    assert b.lines == []
