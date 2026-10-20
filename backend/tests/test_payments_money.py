"""Money arithmetic (app/payments/money.py): integers only, half up in the named places, tiers, periods, proration.
No database."""
from datetime import UTC, datetime, timedelta

import pytest

from app.payments import money
from app.payments.money import Discount, LineIn, Tier


def test_half_up_division_is_exact_integer_arithmetic():
    assert money.div_half_up(5, 2) == 3 and money.div_half_up(4, 2) == 2 and money.div_half_up(7, 3) == 2
    assert money.div_half_up(-5, 2) == -3  # away from zero
    assert money.div_half_up(10**20 + 1, 2) == 5 * 10**19 + 1  # no float anywhere
    with pytest.raises(ValueError):
        money.div_half_up(1, 0)


def test_currencies_and_formatting_follow_the_minor_unit():
    assert money.currency(" USD ") == "usd"
    with pytest.raises(ValueError):
        money.currency("xxx")
    assert money.format_amount(123456, "usd") == "USD 1,234.56"
    assert money.format_amount(1000, "jpy") == "JPY 1,000"  # a zero-decimal currency keeps whole units
    assert money.format_amount(-5, "eur") == "-EUR 0.05"


def test_a_percentage_discount_is_rounded_once_and_spread_so_lines_add_up():
    # 15 % of 3 x 333 = 149.85 -> 150, spread 50/50/50
    t = money.totals([LineIn(333), LineIn(333), LineIn(333)], Discount(percent_bp=1500))
    assert t.discount == 150 and [x.discount for x in t.lines] == [50, 50, 50]
    assert t.total == 999 - 150
    # uneven weights: the largest remainder gets the odd unit, and the parts always sum to the discount
    t = money.totals([LineIn(1000), LineIn(1), LineIn(2)], Discount(percent_bp=3333))
    assert sum(x.discount for x in t.lines) == t.discount == money.div_half_up(1003 * 3333, 10000)


def test_a_fixed_discount_never_goes_below_zero_and_skips_credit_lines():
    t = money.totals([LineIn(500), LineIn(-200, discountable=False)], Discount(amount=10_000))
    assert t.discount == 300 and t.total == 0  # capped at the subtotal after credits
    t = money.totals([LineIn(500, discountable=False), LineIn(400)], Discount(amount=100))
    assert [x.discount for x in t.lines] == [0, 100]


def test_tax_is_per_line_after_discount_exclusive_adds_inclusive_is_inside():
    t = money.totals([LineIn(1000, tax_bp=825), LineIn(999, tax_bp=825)])
    assert [x.tax for x in t.lines] == [83, 82]  # 82.5 -> 83, 82.4175 -> 82
    assert t.tax == 165 and t.total == 1999 + 165
    inc = money.totals([LineIn(1200, tax_bp=2000, tax_inclusive=True)])
    assert inc.tax == 200 and inc.total == 1200  # 1200 includes 20 % VAT of 200
    disc = money.totals([LineIn(1000, tax_bp=1000)], Discount(percent_bp=5000))
    assert disc.lines[0].tax == 50 and disc.total == 550  # tax on what is left after the discount


def test_a_credit_line_gives_back_its_tax():
    t = money.totals([LineIn(1000, tax_bp=1000), LineIn(-400, tax_bp=1000, discountable=False)])
    assert [x.tax for x in t.lines] == [100, -40] and t.total == 660
    neg = money.totals([LineIn(100), LineIn(-300, discountable=False)])
    assert neg.total == -200  # the caller turns this into credit


def test_tiers_graduated_and_volume():
    tiers = [Tier(10, 100), Tier(20, 80, 500), Tier(None, 50)]
    money.check_tiers(tiers)
    assert money.tiered_amount(tiers, "graduated", 0) == 0
    assert money.tiered_amount(tiers, "graduated", 10) == 1000
    assert money.tiered_amount(tiers, "graduated", 15) == 1000 + 5 * 80 + 500
    assert money.tiered_amount(tiers, "graduated", 25) == 1000 + 10 * 80 + 500 + 5 * 50
    assert money.tiered_amount(tiers, "volume", 15) == 15 * 80 + 500
    assert money.tiered_amount(tiers, "volume", 25) == 25 * 50
    for bad in ([], [Tier(10, 1)], [Tier(None, 1), Tier(None, 1)], [Tier(10, 1), Tier(5, 1), Tier(None, 1)],
                [Tier(None, -1)]):
        with pytest.raises(ValueError):
            money.check_tiers(bad)


def test_periods_are_counted_from_the_anchor_so_the_31st_comes_back():
    a = datetime(2027, 1, 31, 9, 30, tzinfo=UTC)
    months = [money.period_boundary(a, "month", 1, n).date().isoformat() for n in range(4)]
    assert months == ["2027-01-31", "2027-02-28", "2027-03-31", "2027-04-30"]
    leap = datetime(2028, 2, 29, tzinfo=UTC)
    assert money.period_boundary(leap, "year", 1, 1).date().isoformat() == "2029-02-28"
    assert money.period_boundary(leap, "year", 1, 4).date().isoformat() == "2032-02-29"
    assert money.period_boundary(a, "week", 2, 1) == a + timedelta(weeks=2)
    assert money.period_boundary(a, "day", 3, 2) == a + timedelta(days=6)
    assert money.period_boundary(a, "month", 3, 1).date().isoformat() == "2027-04-30"


def test_proration_is_by_the_second_and_rounded_once():
    start = datetime(2027, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=30)
    assert money.prorate(3000, start, end, start + timedelta(days=10)) == 2000
    assert money.prorate(1000, start, end, start + timedelta(days=10)) == 667  # 666.67 -> 667
    assert money.prorate(1000, start, end, end) == 0 and money.prorate(1000, start, end, start) == 1000
    assert money.prorate(1000, start, end, start - timedelta(days=5)) == 1000


def test_allocate_is_exact():
    for total, weights in ((10, [1, 1, 1]), (7, [5, 0, 5]), (1, [3, 3]), (0, [1]), (100, [0, 0])):
        parts = money.allocate(total, weights)
        assert sum(parts) == (total if sum(weights) else 0)
        assert all(p == 0 for p, w in zip(parts, weights, strict=True) if w == 0)
