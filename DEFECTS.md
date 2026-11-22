# Defects

Test result: `python -m pytest -q` -> 46 passed.

| # | Where | Problem | Fix |
|---|-------|---------|-----|
| 1 | `repository.get_product`, `get_saved_cart` | SQL built with f-strings, so SQL injection was possible. | Use `?` parameters. |
| 2 | `repository.list_orders` | Never filtered by `user_id`, so users saw everyone's orders. | Added `WHERE user_id = ?`. |
| 3 | `cart.add_item`, `remove_item` | Zero, negative and non-integer quantities were accepted. A negative remove added items. | Quantity must be a positive int, otherwise return `False`. |
| 4 | `cart.add_item` | Stock check ignored what was already in the cart (3 + 3 laptops with stock 5 passed). | Check existing + new quantity against stock. |
| 5 | `cart.apply_discount` | Stored a fixed `discounted_total`, so editing the cart afterwards gave a stale price, and applying a coupon twice stacked it. | Store only the code and recalculate the total each time. A new coupon replaces the old one. |
| 6 | `cart.apply_discount` | `SAVE15` could make the total negative. Float maths also gave odd amounts like 107.83800000000001. | Floor at 0 and calculate in integer cents, rounded to 2 decimals. |
| 7 | `cart.load` | Calling it twice doubled quantities. | Clear the cart before loading. |
| 8 | `checkout.checkout` | Stock was reduced before payment and never put back if the payment was declined or errored. The cart was also cleared on failure. | Reserve stock, charge, and release the stock if payment fails. Clear the cart only when paid. |
| 9 | `checkout.checkout` | Repeating a request charged the customer twice. | `request_id` is required and unique. A repeat returns the original order without charging. |
| 10 | `repository.update_stock` | No stock check, so stock could go negative or be oversold. | `reserve_stock` uses `UPDATE ... WHERE stock >= ?` in one transaction and rolls back if any line fails. Status is `out_of_stock` and nobody is charged. |
| 11 | `checkout.checkout` | Printed the payment token. | Removed. |
| 12 | `repository`, `setup_db` | Connections not closed on errors, and no DB constraints. | Context manager that always closes. Added CHECK, primary key and unique index. |

## Assumptions
- `FREESHIP` is accepted but doesn't change the total (there is no shipping in the model).
- Only one coupon is active at a time.
- After a declined, errored or out-of-stock checkout, a retry needs a new `request_id`.
- Missing `request_id` or payment token is rejected.
- `FakePaymentGateway` is unchanged.

## Tests
`tests/test_cart.py` and `tests/test_checkout.py` cover the fixes above, using temporary SQLite databases and fake gateways.

## CI
`.github/workflows/tests.yml` runs `python -m pytest -q` on every push and pull request.
