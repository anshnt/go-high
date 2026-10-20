"""Money arithmetic for payments (module 21), pure and integer only. Every amount is an int of minor units of one
ISO 4217 currency (cents for USD, yen for JPY), never a float. Rounding is half up (away from zero for the positive
amounts we round) and happens in exactly the places named here, so the server, the hosted pages and the web app agree
to the unit:

- a line's amount is `quantity * unit_amount` (fixed) or the tier sum (tiered): exact, no rounding;
- a percentage discount is rounded once on the discountable subtotal, then spread over the lines it applies to by the
  largest remainder method, so the line discounts add up to the invoice discount exactly;
- tax is worked out per line on the line's amount after its discount, rounded per line, and the invoice tax is the sum
  of the lines' (an inclusive rate takes the tax out of the amount, an exclusive one adds it);
- proration is the price of a period times the share of seconds left, rounded once.

The web app mirrors `format_amount` and the totals in frontend/src/payments/money.ts."""
from dataclasses import dataclass
from datetime import datetime, timedelta

# ISO 4217 currencies we take, with the number of minor unit digits. Zero-decimal currencies keep amounts in whole
# units (1000 JPY is 1000). ponytail: the common ones; add more as people ask (the exponent is all that is needed).
EXPONENTS = {
    "usd": 2, "eur": 2, "gbp": 2, "cad": 2, "aud": 2, "nzd": 2, "chf": 2, "sek": 2, "nok": 2, "dkk": 2, "pln": 2,
    "czk": 2, "huf": 2, "ron": 2, "bgn": 2, "inr": 2, "sgd": 2, "hkd": 2, "mxn": 2, "brl": 2, "zar": 2, "aed": 2,
    "sar": 2, "ils": 2, "try": 2, "php": 2, "thb": 2, "myr": 2, "idr": 2, "cny": 2, "twd": 2,
    "jpy": 0, "krw": 0, "vnd": 0, "clp": 0, "isk": 0, "ugx": 0,
}
MAX_AMOUNT = 99_999_999_99  # one line, one invoice: below what every provider takes (Stripe: 8 digits of dollars)
BP = 10_000  # basis points in one whole: 825 bp is 8.25 %


def currency(code: str) -> str:
    """The lower case code, or ValueError for one we do not take."""
    c = (code or "").strip().lower()
    if c not in EXPONENTS:
        raise ValueError("is not a currency we take")
    return c


def div_half_up(numerator: int, denominator: int) -> int:
    """numerator / denominator rounded half away from zero, in integers (no float ever touches money)."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    q, r = divmod(abs(numerator), denominator)
    if 2 * r >= denominator:
        q += 1
    return q if numerator >= 0 else -q


def format_amount(amount: int, code: str) -> str:
    """`$12.50`-like text for pages and receipts: the code and the amount in major units (`USD 12.50`)."""
    exp = EXPONENTS.get(code.lower(), 2)
    sign = "-" if amount < 0 else ""
    whole, frac = divmod(abs(amount), 10 ** exp) if exp else (abs(amount), 0)
    body = f"{whole:,}" + (f".{frac:0{exp}d}" if exp else "")
    return f"{sign}{code.upper()} {body}"


# --- prices -----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Tier:
    up_to: int | None  # inclusive upper bound of units; None for the last tier (and beyond)
    unit_amount: int = 0
    flat_amount: int = 0


def check_tiers(tiers: list[Tier]) -> None:
    """ValueError unless the tiers rise strictly and only the last is open ended."""
    if not tiers:
        raise ValueError("needs at least one tier")
    last = 0
    for i, t in enumerate(tiers):
        final = i == len(tiers) - 1
        if t.unit_amount < 0 or t.flat_amount < 0:
            raise ValueError("amounts cannot be negative")
        if final != (t.up_to is None):
            raise ValueError("only the last tier is open ended (up_to null), and it must be")
        if not final and (t.up_to is None or t.up_to <= last):
            raise ValueError("each tier must go higher than the one before")
        last = t.up_to or last


def tiered_amount(tiers: list[Tier], mode: str, quantity: int) -> int:
    """The price of `quantity` units. `graduated`: each unit at the rate of the tier it falls in, plus the flat fee of
    every tier reached. `volume`: every unit at the rate of the tier the whole quantity falls in, plus its flat fee."""
    if quantity < 0:
        raise ValueError("quantity cannot be negative")
    if quantity == 0:
        return 0
    if mode == "volume":
        tier = next(t for t in tiers if t.up_to is None or quantity <= t.up_to)
        return quantity * tier.unit_amount + tier.flat_amount
    total, below = 0, 0
    for t in tiers:
        top = quantity if t.up_to is None else min(quantity, t.up_to)
        if top <= below:
            break
        total += (top - below) * t.unit_amount + t.flat_amount
        below = top
    return total


# --- invoices ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class LineIn:
    amount: int  # quantity times unit amount, or the tiered amount; negative for a credit line
    tax_bp: int = 0  # 0..10000 basis points
    tax_inclusive: bool = False
    discountable: bool = True  # the coupon applies to this line


@dataclass(frozen=True)
class LineOut:
    amount: int
    discount: int
    tax: int
    total: int  # what the line adds to the invoice: amount - discount + exclusive tax


@dataclass(frozen=True)
class Totals:
    lines: list[LineOut]
    subtotal: int  # sum of line amounts (inclusive tax still inside them)
    discount: int
    tax: int  # every line's tax, inclusive and exclusive
    total: int  # what the customer pays: subtotal - discount + exclusive tax


@dataclass(frozen=True)
class Discount:
    percent_bp: int | None = None  # 1..10000
    amount: int | None = None  # minor units of the invoice's currency


def allocate(total: int, weights: list[int]) -> list[int]:
    """Splits `total` over the weights in proportion, rounding by the largest remainder so the parts add up exactly.
    Ties go to the earlier line."""
    whole = sum(weights)
    if total == 0 or whole <= 0:
        return [0] * len(weights)
    parts = [total * w // whole for w in weights]
    order = sorted(range(len(weights)), key=lambda i: (-(total * weights[i] % whole), i))
    for i in order[: total - sum(parts)]:
        parts[i] += 1
    return parts


def line_tax(amount: int, bp: int, inclusive: bool) -> int:
    """The tax in (inclusive) or on (exclusive) a line's amount. A credit line (negative) gives back the tax of the same
    positive amount, so crediting what was charged returns its tax too."""
    if amount < 0:
        return -line_tax(-amount, bp, inclusive)
    if amount == 0 or bp <= 0:
        return 0
    if inclusive:
        return amount - div_half_up(amount * BP, BP + bp)
    return div_half_up(amount * bp, BP)


def totals(lines: list[LineIn], discount: Discount | None = None) -> Totals:
    """Subtotal, discount, tax and total of an invoice, line by line (see the rules at the top of this module). A
    discount never takes the invoice below zero and never applies to a credit line (a negative amount), which carries
    its own (negative) tax. The total can be negative when credits outweigh charges; the caller turns that into a
    credit balance."""
    subtotal = sum(line.amount for line in lines)
    weights = [line.amount if line.discountable and line.amount > 0 else 0 for line in lines]
    base = sum(weights)
    off = 0
    if discount and base > 0:
        if discount.percent_bp:
            off = div_half_up(base * discount.percent_bp, BP)
        elif discount.amount:
            off = discount.amount
        off = max(0, min(off, base, max(subtotal, 0)))
    shares = allocate(off, weights)
    out = []
    for line, share in zip(lines, shares, strict=True):
        net = line.amount - share
        tax = line_tax(net, line.tax_bp, line.tax_inclusive)
        out.append(LineOut(line.amount, share, tax, net + (0 if line.tax_inclusive else tax)))
    total = sum(o.total for o in out)
    return Totals(out, subtotal, off, sum(o.tax for o in out), total)


# --- billing periods --------------------------------------------------------------------------------------------

INTERVALS = ("day", "week", "month", "year")


def add_months(anchor: datetime, months: int) -> datetime:
    """`anchor` moved by whole months, the day clamped to the month's last (Jan 31 + 1 month is Feb 28 or 29)."""
    month0 = anchor.month - 1 + months
    year, month = anchor.year + month0 // 12, month0 % 12 + 1
    nxt = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=anchor.tzinfo)
    last = (nxt - timedelta(days=1)).day
    return anchor.replace(year=year, month=month, day=min(anchor.day, last))


def period_boundary(anchor: datetime, interval: str, count: int, n: int) -> datetime:
    """The start of period `n` (0 is the anchor) of a schedule billed every `count` `interval`s. Always counted from the
    anchor, never from the previous boundary, so a subscription that started on the 31st bills on the 31st whenever
    the month has one (31 Jan, 29 Feb, 31 Mar), instead of drifting to the 28th for good."""
    if interval == "day":
        return anchor + timedelta(days=count * n)
    if interval == "week":
        return anchor + timedelta(weeks=count * n)
    if interval == "month":
        return add_months(anchor, count * n)
    if interval == "year":
        return add_months(anchor, 12 * count * n)
    raise ValueError(f"unknown interval {interval!r}")


def prorate(amount: int, start: datetime, end: datetime, at: datetime) -> int:
    """The part of `amount` (the price of the period [start, end)) that the time from `at` to the end is worth, by the
    second, rounded half up. 0 at or after the end, the whole amount at or before the start."""
    whole = int((end - start).total_seconds())
    left = int((end - max(at, start)).total_seconds())
    if whole <= 0 or left <= 0:
        return 0
    return div_half_up(amount * min(left, whole), whole)
