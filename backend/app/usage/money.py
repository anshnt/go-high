"""Money for the usage ledger: integers only, never floats. Every amount is in **micros**, millionths of the currency's
major unit (1 USD = 1_000_000), so a carrier rate of 0.79 cents per SMS segment is exact (7_900) and summing a million
of them loses nothing. What a person pays or sets (a top-up, a cap, a threshold, a balance adjustment) must be a whole
number of the currency's minor units (cents for USD, yen for JPY), which `whole_minor` checks; a payment provider is
asked for minor units (`to_minor`). The one place a fraction can appear is a percentage markup, which rounds half up to
the micro (`with_markup`)."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MICROS = 1_000_000
# ISO 4217 currencies whose minor unit is not a hundredth; every other code has two decimals.
EXPONENTS = {"JPY": 0, "KRW": 0, "VND": 0, "CLP": 0, "ISK": 0, "UGX": 0, "XAF": 0, "XOF": 0,
             "BHD": 3, "KWD": 3, "OMR": 3, "JOD": 3, "TND": 3}
CURRENCIES = ("USD", "EUR", "GBP", "CAD", "AUD", "NZD", "INR", "SGD", "AED", "ZAR", "BRL", "MXN", "CHF", "SEK", "NOK",
              "DKK", "PLN", "JPY", "KWD")  # what a wallet may hold; the provider must be able to charge it


def exponent(currency: str) -> int:
    return EXPONENTS.get(currency, 2)


def minor_step(currency: str) -> int:
    """Micros in one minor unit: 10_000 for USD (a cent), 1_000_000 for JPY (a yen)."""
    return MICROS // 10 ** exponent(currency)


def whole_minor(micros: int, currency: str) -> bool:
    return micros % minor_step(currency) == 0


def to_minor(micros: int, currency: str) -> int:
    """Minor units of an amount that `whole_minor` accepted."""
    if not whole_minor(micros, currency):
        raise ValueError(f"{micros} micros is not a whole number of {currency} minor units")
    return micros // minor_step(currency)


def from_major(value) -> int:
    """Micros of a decimal amount in major units given as text or a number ("0.0079" -> 7_900), rounded half up. Used
    for the channels' `segment_cost`, which is stored as text."""
    try:
        return int((Decimal(str(value)) * MICROS).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return 0


def with_markup(cost: int, markup_bp: int) -> int:
    """`cost` plus a markup in basis points (2_500 is 25 %), rounded half up to the micro; never below zero."""
    total = cost * (10_000 + markup_bp)
    return max(0, (total + 5_000) // 10_000) if total >= 0 else 0


def show(micros: int, currency: str) -> str:
    """For text a person reads (a refusal, a notification): "$0.0158", "USD 12.50"; at least the minor digits, more when
    the amount has them (up to six)."""
    sign, value = ("-" if micros < 0 else ""), abs(micros)
    places = max(exponent(currency), len(str(value % MICROS).rjust(6, "0").rstrip("0")))
    text = f"{value // MICROS}" + (f".{str(value % MICROS).rjust(6, '0')[:places]}" if places else "")
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency)
    return f"{sign}{symbol}{text}" if symbol else f"{sign}{currency} {text}"
