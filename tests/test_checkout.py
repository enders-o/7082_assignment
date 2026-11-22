"""Unit tests for CheckoutService and StoreRepository (corrected behaviour)."""
import pytest

from cart import ShoppingCart
from checkout import CheckoutService
from payments import FakePaymentGateway
from repository import StoreRepository
from setup_db import initialize


class ExplodingGateway:
    """Fake gateway that raises an unexpected error."""
    def __init__(self):
        self.calls = 0

    def charge(self, amount, payment_token):
        self.calls += 1
        raise RuntimeError('network down')


@pytest.fixture
def repo(tmp_path):
    db = str(tmp_path / 'test.db')
    initialize(db)
    return StoreRepository(db)


def stock(repo, sku):
    return repo.get_product(sku).stock


def make_cart(repo, user='alice', sku='MOU-01', qty=2):
    cart = ShoppingCart(user, repo)
    assert cart.add_item(sku, qty)
    return cart


# ---- repository -----------------------------------------------------------

def test_sql_injection_in_sku_is_harmless(repo):
    assert repo.get_product("x' OR '1'='1") is None
    assert repo.get_product("MOU-01' OR '1'='1") is None


def test_sql_injection_in_user_id_does_not_leak_other_carts(repo):
    cart = ShoppingCart('alice', repo)
    cart.add_item('USB-01', 1)
    cart.save()
    assert repo.get_saved_cart("' OR '1'='1") == []


def test_list_orders_only_returns_that_users_orders(repo):
    gw = FakePaymentGateway()
    svc = CheckoutService(repo, gw)
    svc.checkout(make_cart(repo, 'alice'), 'tok', 'r1')
    svc.checkout(make_cart(repo, 'bob'), 'tok', 'r2')
    assert [o[1] for o in repo.list_orders('alice')] == ['alice']
    assert [o[1] for o in repo.list_orders('bob')] == ['bob']


def test_reserve_stock_is_all_or_nothing(repo):
    cart = ShoppingCart('alice', repo)
    cart.add_item('USB-01', 5)
    cart.add_item('LAP-01', 5)
    # Someone else buys laptops first.
    other = make_cart(repo, 'bob', 'LAP-01', 3)
    assert repo.reserve_stock(other.lines)
    assert repo.reserve_stock(cart.lines) is False
    assert stock(repo, 'USB-01') == 50  # USB reservation rolled back
    assert stock(repo, 'LAP-01') == 2


# ---- checkout -------------------------------------------------------------

def test_checkout_empty_cart(repo):
    gw = FakePaymentGateway()
    result = CheckoutService(repo, gw).checkout(ShoppingCart('alice', repo), 'tok', 'r1')
    assert result.status == 'empty'
    assert result.order_id is None
    assert gw.calls == []


def test_successful_checkout_charges_once_and_updates_state(repo):
    gw = FakePaymentGateway()
    cart = make_cart(repo)
    cart.apply_discount('WELCOME10')
    result = CheckoutService(repo, gw).checkout(cart, 'tok', 'r1')
    assert result.status == 'paid'
    assert result.total == 53.91  # 59.90 * 0.9 = 53.91
    assert gw.calls == [(53.91, 'tok')]
    assert stock(repo, 'MOU-01') == 18
    assert cart.lines == [] and cart.discount_code is None
    assert repo.get_saved_cart('alice') == []
    assert repo.list_orders('alice')[0][3] == 'paid'


def test_declined_payment_restores_stock_and_keeps_cart(repo):
    gw = FakePaymentGateway(should_approve=False)
    cart = make_cart(repo)
    result = CheckoutService(repo, gw).checkout(cart, 'tok', 'r1')
    assert result.status == 'declined'
    assert stock(repo, 'MOU-01') == 20  # not lost
    assert len(cart.lines) == 1          # user can retry
    assert repo.list_orders('alice')[0][3] == 'declined'


def test_unexpected_payment_error_restores_stock(repo):
    gw = ExplodingGateway()
    cart = make_cart(repo)
    result = CheckoutService(repo, gw).checkout(cart, 'tok', 'r1')
    assert result.status == 'payment_error'
    assert stock(repo, 'MOU-01') == 20
    assert len(cart.lines) == 1


def test_repeated_request_id_does_not_charge_or_decrement_twice(repo):
    gw = FakePaymentGateway()
    svc = CheckoutService(repo, gw)
    first = svc.checkout(make_cart(repo), 'tok', 'same-id')
    second = svc.checkout(make_cart(repo), 'tok', 'same-id')  # client retry
    assert second.order_id == first.order_id
    assert second.status == 'paid'
    assert len(gw.calls) == 1
    assert stock(repo, 'MOU-01') == 18
    assert len(repo.list_orders('alice')) == 1


def test_request_id_cannot_be_reused_by_another_user(repo):
    gw = FakePaymentGateway()
    svc = CheckoutService(repo, gw)
    svc.checkout(make_cart(repo, 'alice'), 'tok', 'shared')
    result = svc.checkout(make_cart(repo, 'mallory'), 'tok', 'shared')
    assert result.status == 'duplicate_request'
    assert len(gw.calls) == 1


def test_checkout_fails_when_stock_vanished_after_adding_to_cart(repo):
    gw = FakePaymentGateway()
    cart = make_cart(repo, 'alice', 'LAP-01', 4)
    # Another customer buys 3 laptops while alice's cart is open.
    repo.reserve_stock(make_cart(repo, 'bob', 'LAP-01', 3).lines)
    result = CheckoutService(repo, gw).checkout(cart, 'tok', 'r1')
    assert result.status == 'out_of_stock'
    assert gw.calls == []            # never charged
    assert stock(repo, 'LAP-01') == 2  # unchanged by this checkout


@pytest.mark.parametrize('request_id', [None, ''])
def test_missing_request_id_is_rejected_without_side_effects(repo, request_id):
    gw = FakePaymentGateway()
    result = CheckoutService(repo, gw).checkout(make_cart(repo), 'tok', request_id)
    assert result.status == 'missing_request_id'
    assert gw.calls == [] and stock(repo, 'MOU-01') == 20


def test_missing_payment_token_is_rejected(repo):
    gw = FakePaymentGateway()
    result = CheckoutService(repo, gw).checkout(make_cart(repo), '', 'r1')
    assert result.status == 'invalid_payment'
    assert gw.calls == []


def test_payment_token_is_not_printed(repo, capsys):
    CheckoutService(repo, FakePaymentGateway()).checkout(make_cart(repo), 'SECRET-TOKEN-123', 'r1')
    out = capsys.readouterr()
    assert 'SECRET-TOKEN-123' not in out.out + out.err


def test_discount_edit_before_checkout_is_charged_correctly(repo):
    gw = FakePaymentGateway()
    cart = make_cart(repo, qty=2)
    cart.apply_discount('STUDENT20')
    cart.add_item('MOU-01', 3)  # edit AFTER discount: 5 * 29.95 = 149.75 -> 119.80
    result = CheckoutService(repo, gw).checkout(cart, 'tok', 'r1')
    assert result.total == 119.80
    assert gw.calls[0][0] == 119.80
