"""The integer money rules of the usage ledger (no database)."""
import pytest

from app.usage import money, pricing, sending
from app.usage.models import Wallet
from app.usage.wallet import Verdict, judge


def test_micros_are_exact_for_sub_cent_rates_and_round_half_up_only_for_markups():
    assert money.from_major("0.0079") == 7_900
    assert money.from_major("0.00000049") == 0 and money.from_major("0.0000005") == 1  # half up to the micro
    assert money.from_major("not a number") == 0
    assert money.with_markup(7_900, 2_500) == 9_875  # 25 %
    assert money.with_markup(1, 5_000) == 2  # 1.5 rounds half up
    assert money.with_markup(3, 3_333) == 4  # 3.9999 -> 4
    assert money.with_markup(7_900, -10_000) == 0  # free
    assert money.with_markup(0, 1_000_000) == 0


def test_minor_units_depend_on_the_currency():
    assert money.minor_step("USD") == 10_000 and money.minor_step("JPY") == 1_000_000
    assert money.minor_step("KWD") == 1_000
    assert money.whole_minor(5 * money.MICROS, "USD") and not money.whole_minor(1_005_000 + 1, "USD")
    assert money.whole_minor(1_010_000, "USD") and not money.whole_minor(1_010_000, "JPY")
    assert money.to_minor(12_340_000, "USD") == 1_234 and money.to_minor(3_000_000, "JPY") == 3
    with pytest.raises(ValueError):
        money.to_minor(1, "USD")


def test_amounts_read_well_for_people():
    assert money.show(15_800, "USD") == "$0.0158"
    assert money.show(12_500_000, "USD") == "$12.50"
    assert money.show(-1_000_000, "EUR") == "-€1.00"
    assert money.show(3_000_000, "JPY") == "JPY 3"
    assert money.show(0, "USD") == "$0.00"


def wallet(**kw) -> Wallet:
    return Wallet(**({"currency": "USD", "balance": 0, "mode": "prepaid", "credit_limit": None, "low_balance_at": None,
                      "monthly_cap": None, "cap_alert_pct": 80} | kw))


def test_the_judge_blocks_or_warns_by_mode_limit_and_cap():
    assert judge(wallet(), 0, 0) == Verdict()  # nothing to pay is never refused, even from an empty wallet
    assert judge(wallet(), 1, 0).code == "wallet_empty"
    assert judge(wallet(balance=10), 10, 0).allowed  # exactly enough
    assert judge(wallet(balance=10), 11, 0).code == "wallet_empty"
    owing = judge(wallet(mode="postpaid"), 5 * money.MICROS, 0)
    assert owing.allowed and owing.warnings == ["The wallet balance will be -$5.00."]
    assert judge(wallet(mode="postpaid", credit_limit=money.MICROS), money.MICROS, 0).allowed
    assert judge(wallet(mode="postpaid", credit_limit=money.MICROS), money.MICROS + 1, 0).code == "credit_limit"
    capped = judge(wallet(balance=100 * money.MICROS, monthly_cap=10 * money.MICROS), money.MICROS, 9_500_000)
    assert capped.code == "usage_cap" and "$10.00" in capped.reason
    near = judge(wallet(balance=100 * money.MICROS, monthly_cap=10 * money.MICROS), money.MICROS, 7 * money.MICROS)
    assert near.allowed and near.warnings == ["This month's usage will be $8.00 of the $10.00 cap."]
    low = judge(wallet(balance=2 * money.MICROS, low_balance_at=money.MICROS * 3 // 2), money.MICROS, 0)
    assert low.allowed and "below the alert at $1.50" in low.warnings[0]


class Ch:
    def __init__(self, kind, **config):
        self.kind, self.config = kind, config


def test_a_message_counts_its_units_by_channel_kind():
    assert sending.items(Ch("sms", segment_cost="0.0079"), "x" * 161, 500) == [("sms.segment", 1000, 7_900)]
    assert sending.items(Ch("sms"), "hi", 1) == [("sms.segment", 1, None)]
    assert sending.items(Ch("email"), "x" * 5000, 3) == [("email.message", 3, None)]
    assert sending.items(Ch("whatsapp", segment_cost=""), "hi") == [("whatsapp.message", 1, None)]
    assert sending.items(Ch("webchat"), "hi") == []


def test_a_markup_hook_has_the_last_word_on_the_price_but_never_the_cost(monkeypatch):
    q = pricing.Quote("sms.segment", 2, 7_900, 7_900)
    monkeypatch.setattr(pricing, "HOOKS", [lambda ws, org, brand, q: pricing.Quote(q.meter, q.quantity, 1, 10_000)])

    class Db:
        def scalar(self, _):
            return None

    class Ws:
        id = org_id = brand_id = None

    got = pricing.quote(Db(), Ws(), "USD", "sms.segment", 2, 7_900)
    assert (got.unit_cost, got.unit_price, got.price, got.basis) == (7_900, 10_000, 20_000, "hook")
    assert q.cost == 15_800
    with pytest.raises(ValueError):
        pricing.quote(Db(), Ws(), "USD", "fax.page", 1)
