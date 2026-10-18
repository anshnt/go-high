"""Field types (ADR 0002). `validate(field, value)` is the one place a value is checked and normalized for its field,
so the API, imports, forms and workflows cannot disagree. `check_options` and `check_rules` do the same for a field's
own settings. Operators say which filter operations a type supports (see filters.py)."""
import math
import re
import uuid
import zoneinfo
from collections.abc import Callable
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import NamedTuple
from urllib.parse import urlsplit

import phonenumbers

from .. import config

TEXT_CAP, LONG_TEXT_CAP, EMAIL_CAP, URL_CAP = 1000, 20000, 254, 2000
MAX_CHOICES = 200
MAX_MONEY = 10**15  # minor units; keeps sums and casts far from overflow
ISO_4217 = frozenset(
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD CAD CDF CHF "
    "CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG "
    "HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA "
    "MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD "
    "RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX "
    "USD UYU UZS VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWG".split())
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
CHOICE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")

# Filter operators per kind of type; the compiler checks every operator against its field's set.
TEXTY = frozenset({"is", "is_not", "contains", "starts_with", "in", "not_in", "is_empty", "is_not_empty"})
NUMBERY = frozenset({"is", "is_not", "gt", "gte", "lt", "lte", "between", "in", "not_in", "is_empty", "is_not_empty"})
TIMEY = frozenset({"is", "is_not", "gt", "gte", "lt", "lte", "between", "within_last", "older_than", "is_empty",
                   "is_not_empty"})
FLAG = frozenset({"is", "is_not", "is_empty", "is_not_empty"})
PICK = frozenset({"is", "is_not", "in", "not_in", "is_empty", "is_not_empty"})
MULTI = frozenset({"contains", "in", "not_in", "is_empty", "is_not_empty"})
COMPUTED = frozenset()
CHOICES = ("select", "multi_select", "stage")
TEXT_LIKE = ("text", "long_text", "email", "phone", "url")


def text_field(cap: int, fix: Callable[[str], str] = str.strip) -> Callable:
    def check(field, value):
        if not isinstance(value, str) or "\x00" in value:  # Postgres text and jsonb cannot hold NUL
            raise ValueError("must be text")
        value = fix(value)
        top = min(field.rules.get("max_length", cap), cap)
        if len(value) > top:
            raise ValueError(f"must be at most {top} characters")
        if len(value) < field.rules.get("min_length", 0):
            raise ValueError(f"must be at least {field.rules['min_length']} characters")
        return value
    return check


@lru_cache
def zone_names() -> dict[str, str]:
    return {z.lower(): z for z in zoneinfo.available_timezones()}


def plain_text(field, value):
    """Text; with the rule `timezone`, an IANA zone name such as America/New_York, stored in its canonical spelling."""
    value = text_field(TEXT_CAP)(field, value)
    if field.rules.get("timezone"):
        zone = zone_names().get(value.lower())
        if zone is None:
            raise ValueError("is not a time zone (an IANA name like America/New_York)")
        return zone
    return value


def email(field, value):
    value = text_field(EMAIL_CAP, lambda v: v.strip().lower())(field, value)
    if not EMAIL.fullmatch(value):
        raise ValueError("is not an email address")
    return value


def url(field, value):
    value = text_field(URL_CAP)(field, value)
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc or re.search(r"\s", value):
        raise ValueError("must be an http or https URL")
    return value


def phone(field, value):
    """E.164, parsed with the field's region (options.region) or the default; numbers that start with + need none."""
    value = text_field(40)(field, value)
    region = str(field.options.get("region") or config.DEFAULT_PHONE_REGION).upper()
    try:
        number = phonenumbers.parse(value, region)
    except phonenumbers.NumberParseException:
        raise ValueError("is not a phone number") from None
    # Possible, not valid: strict validity refuses real numbers in ranges newer than the bundled metadata, and an
    # import must never drop a customer's number for that. Length and country code are still checked.
    if not phonenumbers.is_possible_number(number):
        raise ValueError(f"is not a valid phone number (default country {region}; start with + and the country code)")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def number(field, value):
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError("must be a number")
    if abs(value) > MAX_MONEY:
        raise ValueError("is out of range")
    rules = field.rules
    if rules.get("integer") and value != int(value):
        raise ValueError("must be a whole number")
    if "min" in rules and value < rules["min"]:
        raise ValueError(f"must be at least {rules['min']}")
    if "max" in rules and value > rules["max"]:
        raise ValueError(f"must be at most {rules['max']}")
    return int(value) if isinstance(value, float) and value.is_integer() else value


def money(field, value):
    """{"amount": integer minor units (cents), "currency": ISO 4217}; the currency defaults to options.currency."""
    if not isinstance(value, dict) or set(value) - {"amount", "currency"}:
        raise ValueError('must look like {"amount": 1999, "currency": "USD"} (amount in minor units)')
    amount, currency = value.get("amount"), str(value.get("currency") or field.options.get("currency", "USD")).upper()
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValueError("amount must be a whole number of minor units, like cents")
    if abs(amount) > MAX_MONEY:
        raise ValueError("amount is out of range")
    if currency not in ISO_4217:
        raise ValueError(f"currency {currency!r} is not an ISO 4217 code")
    if "min" in field.rules and amount < field.rules["min"]:
        raise ValueError(f"amount must be at least {field.rules['min']}")
    if "max" in field.rules and amount > field.rules["max"]:
        raise ValueError(f"amount must be at most {field.rules['max']}")
    return {"amount": amount, "currency": currency}


def day(field, value):
    if not isinstance(value, str) or not DATE.fullmatch(value.strip()):
        raise ValueError("must be a date like 2026-10-17")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise ValueError("is not a real date") from None


def moment(field, value):
    """ISO 8601 with a time zone offset or Z; stored in UTC."""
    try:
        parsed = datetime.fromisoformat(value.strip()) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None or len(value) < 11:
        raise ValueError("must be a date and time with a zone, like 2026-10-17T09:30:00Z")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def boolean(field, value):
    if not isinstance(value, bool):
        raise ValueError("must be true or false")
    return value


def choice_ids(field) -> set[str]:
    return {c["id"] for c in field.options.get("choices", [])}


def choice(field, value):
    if not isinstance(value, str) or value not in choice_ids(field):
        raise ValueError("is not one of the field's choices")
    return value


def choices(field, value):
    if not isinstance(value, list):
        raise ValueError("must be a list of choices")
    if len(value) > field.rules.get("max_items", MAX_CHOICES):
        raise ValueError(f"has more than {field.rules.get('max_items', MAX_CHOICES)} choices")
    return list(dict.fromkeys(choice(field, v) for v in value))


def ident(field, value):
    """A user, record or stage id; whether it exists is checked by the write path, which has the database."""
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise ValueError("must be an id") from None


def computed(field, value):
    raise ValueError("is computed and read-only")


class Kind(NamedTuple):
    check: Callable
    ops: frozenset
    rules: frozenset = frozenset()  # rule names beyond `required`
    options: frozenset = frozenset()


# ponytail: formula and rollup are stored and listed but never computed; they refuse writes and filters until the
# evaluator exists (ADR 0002: computed on read first, materialized on write when lists need it).
# A `stage` value is the id of a stage (module 10); that it exists in this workspace is checked by the write path, which
# has the database, like the people and records a `user` or `record` value names.
TYPES: dict[str, Kind] = {
    "text": Kind(plain_text, TEXTY, frozenset({"min_length", "max_length", "timezone"})),
    "long_text": Kind(text_field(LONG_TEXT_CAP), TEXTY, frozenset({"min_length", "max_length"})),
    "number": Kind(number, NUMBERY, frozenset({"min", "max", "integer"})),
    "money": Kind(money, NUMBERY, frozenset({"min", "max"}), frozenset({"currency"})),
    "date": Kind(day, TIMEY),
    "datetime": Kind(moment, TIMEY),
    "boolean": Kind(boolean, FLAG),
    "select": Kind(choice, PICK, options=frozenset({"choices"})),
    "multi_select": Kind(choices, MULTI, frozenset({"max_items"}), frozenset({"choices"})),
    "email": Kind(email, TEXTY, frozenset({"min_length", "max_length"})),
    "phone": Kind(phone, TEXTY, options=frozenset({"region"})),
    "url": Kind(url, TEXTY, frozenset({"min_length", "max_length"})),
    "user": Kind(ident, PICK),
    "record": Kind(ident, PICK, options=frozenset({"object"})),
    "stage": Kind(ident, PICK),
    "formula": Kind(computed, COMPUTED, options=frozenset({"expression"})),
    "rollup": Kind(computed, COMPUTED, options=frozenset({"association", "field", "function"})),
}
# ponytail: a stage field is not sortable; ordering by stage means ordering by stages.position, which needs a join
SORTABLE = ("text", "long_text", "number", "money", "date", "datetime", "boolean", "select", "email", "phone", "url")


def validate(field, value):
    """The normalized value of `field` (anything with .type, .options and .rules), or None for an empty one (the caller
    drops the key). Raises ValueError with a message that finishes the sentence "<field> ...". Read-only types raise."""
    kind = TYPES[field.type]
    if kind.ops is COMPUTED:
        computed(field, value)
    if value is None or value == [] or value == {} or (isinstance(value, str) and not value.strip()):
        return None
    return kind.check(field, value)


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40] or "choice"


def clean_choices(raw) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > MAX_CHOICES:
        raise ValueError(f"choices must be a list of at most {MAX_CHOICES} {{id, label, color}} objects")
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) - {"id", "label", "color"} or not str(item.get("label", "")).strip():
            raise ValueError("each choice needs a label (and may have an id and a color)")
        label = str(item["label"]).strip()[:100]
        taken = {c["id"] for c in out}
        id_ = item.get("id") or slug(label)
        if not isinstance(id_, str) or not CHOICE_ID.fullmatch(id_):
            raise ValueError(f"choice id {id_!r} must be lower case letters, digits, - or _")
        if item.get("id") is None:  # a generated id never collides; an explicit one that does is an error
            id_ = next(i for i in (id_, *(f"{id_}_{n}"[:40] for n in range(2, 10**6))) if i not in taken)
        elif id_ in taken:
            raise ValueError(f"choice id {id_!r} is used twice")
        out.append({"id": id_, "label": label, **({"color": str(item["color"])[:20]} if item.get("color") else {})})
    return out


def check_options(type_: str, options) -> dict:
    """The field's type settings, normalized: select choices, money currency, phone region, the linked object."""
    kind = TYPES[type_]
    if not isinstance(options, dict):
        raise ValueError("must be an object")
    if unknown := sorted(set(options) - kind.options):
        raise ValueError(f"{type_} fields have no option {unknown[0]!r}")
    out = dict(options)
    if "choices" in kind.options:
        out["choices"] = clean_choices(options.get("choices", []))
    if type_ == "money":
        out["currency"] = str(options.get("currency", "USD")).upper()
        if out["currency"] not in ISO_4217:
            raise ValueError(f"currency {out['currency']!r} is not an ISO 4217 code")
    if type_ == "phone" and "region" in options:
        out["region"] = str(options["region"]).upper()
        if out["region"] not in phonenumbers.SUPPORTED_REGIONS:
            raise ValueError(f"region {options['region']!r} is not an ISO 3166 country code")
    if type_ == "record" and not (isinstance(options.get("object"), str) and options["object"]):
        raise ValueError("record fields need the key of the object they link to")
    return out


def check_rules(type_: str, rules) -> dict:
    """Validation rules: `required` for every type, plus the type's own (lengths, min and max, max_items).
    ponytail: conditional required and conditional visibility rules (filter AST over the record) are not enforced yet;
    they arrive with the record form UI, and the compiler can evaluate them then."""
    if not isinstance(rules, dict):
        raise ValueError("must be an object")
    if unknown := sorted(set(rules) - TYPES[type_].rules - {"required"}):
        raise ValueError(f"{type_} fields have no rule {unknown[0]!r}")
    for name, value in rules.items():
        if name in ("required", "integer", "timezone") and not isinstance(value, bool):
            raise ValueError(f"{name} must be true or false")
        if name not in ("required", "integer", "timezone") and (
                isinstance(value, bool) or not isinstance(value, int | float)):
            raise ValueError(f"{name} must be a number")
    return dict(rules)
