"""Messaging compliance rules as pure functions (module 14, ADR 0005). No database: callers pass what they know."""
import re
from datetime import UTC, datetime, time, timedelta, tzinfo
from typing import Literal, NamedTuple
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import phonenumbers
from phonenumbers import timezone

# The standard carrier keyword lists (CTIA, as Twilio and Telnyx apply them).
STOP = frozenset({"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "REVOKE", "OPTOUT"})
START = frozenset({"START", "YES", "UNSTOP"})
HELP = frozenset({"HELP", "INFO"})


def keyword(body: str) -> Literal["stop", "start", "help"] | None:
    """The opt-out, opt-in or help keyword a message consists of, ignoring case and surrounding whitespace and
    punctuation ("Stop." and "STOP!" opt out: honoring more opt-outs is the safe side). The rest of the message must
    be the keyword alone, so "please stop" is an ordinary message."""
    word = re.sub(r"^[\W_]+|[\W_]+$", "", body).upper()
    return "stop" if word in STOP else "start" if word in START else "help" if word in HELP else None


def quiet_until(now: datetime, tz: str | tzinfo, start: str = "21:00", end: str = "08:00") -> datetime | None:
    """None when `now` is outside quiet hours in `tz` (the contact's time zone, an IANA name); else the next moment
    sending is allowed, an aware datetime in `tz`. The window runs from `start` to `end` on the local wall clock and
    may cross midnight (the default); start == end means no quiet hours. The end is placed on the calendar by wall
    clock and converted through UTC, so the hour a DST change adds or removes is accounted for."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    local = now.astimezone(zone)
    begin, finish, at = time.fromisoformat(start), time.fromisoformat(end), local.time()
    if begin == finish:
        return None
    wraps = begin > finish
    if not ((begin <= at or at < finish) if wraps else begin <= at < finish):
        return None
    day = local.date() + timedelta(days=int(wraps and at >= begin))
    return datetime.combine(day, finish, zone).astimezone(UTC).astimezone(zone)  # a time in a DST gap moves forward


def phone_zones(e164: str) -> tuple[str, ...]:
    """The time zones a phone number may be in (an area code usually gives one, a country with no area detail
    several), or none when it cannot be told."""
    try:
        zones = timezone.time_zones_for_number(phonenumbers.parse(e164, None))
    except phonenumbers.NumberParseException:
        return ()
    return tuple(z for z in zones if z != "Etc/Unknown")


class Consent(NamedTuple):
    status: Literal["opted_in", "opted_out", "dnd"]
    source: str  # stop, start, unsubscribe, complaint, manual
    changed_at: datetime


class Refusal(NamedTuple):
    code: str  # opted_out, dnd, quiet_hours, frequency_cap
    reason: str  # shown to the person composing
    retry_at: datetime | None = None  # when sending is allowed again, if waiting helps


OPT_OUT_SOURCES = {"stop": "STOP", "unsubscribe": "unsubscribe", "complaint": "a spam complaint", "manual": "staff"}
QUIET_KINDS = frozenset({"sms", "whatsapp"})
REPLY_WINDOW = timedelta(hours=24)  # a contact who wrote this recently may be answered at any hour


def can_send(kind: str, now: datetime, *, consent: Consent | None = None, zones: tuple[str, ...] = (),
             quiet: tuple[str, str] = ("21:00", "08:00"), replying: bool = False, sent: int = 0,
             cap: tuple[int, int] | None = None) -> Refusal | None:
    """None when a message on a channel of this `kind` may go to the contact now, else why not. `consent` is the
    contact's row for the kind, `zones` the contact's time zones (several when unsure: any of them in quiet hours
    waits for the latest end), `replying` that the contact wrote within REPLY_WINDOW, `sent` the messages sent to
    them on the channel in the cap's window and `cap` (max, hours). Quiet hours only bind SMS and WhatsApp.
    ponytail: A2P registration status of the sending number (ADR 0005) is not checked until the wizard exists."""
    if consent and consent.status == "opted_out":
        when = consent.changed_at
        source = OPT_OUT_SOURCES.get(consent.source, consent.source)
        return Refusal("opted_out", f"Opted out by {source} on {when:%b} {when.day}")
    if consent and consent.status == "dnd":
        return Refusal("dnd", f"Do not disturb is on for {kind}")
    if kind in QUIET_KINDS and not replying:
        waits = []
        for zone in zones:
            try:
                if until := quiet_until(now, zone, *quiet):
                    waits.append((until, zone))
            except (KeyError, ValueError):  # a name that is not a time zone: treated as unknown
                continue
        if waits:
            until, zone = max(waits)
            return Refusal("quiet_hours", f"Quiet hours for this contact ({zone}): sending resumes at "
                                          f"{until:%H:%M}", until)
    if cap and cap[0] and sent >= cap[0]:
        return Refusal("frequency_cap", f"Frequency cap reached: {cap[0]} messages in {cap[1]} hours")
    return None


# GSM 03.38: the basic table, and the extension table whose characters take an escape plus the character.
GSM_BASIC = ("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZ"
             "ÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM_EXTENSION = "\f^{}\\[~]|€"
LIMITS = {"gsm7": (160, 153), "ucs2": (70, 67)}  # characters in one message, per part of a longer one


def sms_segments(body: str) -> tuple[Literal["gsm7", "ucs2"], int, int]:
    """(encoding, segments, chars) as carriers count them. GSM-7 when every character is in the basic or extension
    table (extension characters such as { } [ ] \\ ^ ~ | and the euro sign cost two), else UCS-2 where a character
    outside the basic plane, an emoji for one, is two units. 160 GSM-7 characters or 70 UCS-2 units fit one segment;
    longer text takes 153 or 67 per segment, and a two-unit character is never split across segments."""
    if all(c in GSM_BASIC or c in GSM_EXTENSION for c in body):
        encoding, widths = "gsm7", [2 if c in GSM_EXTENSION else 1 for c in body]
    else:
        encoding, widths = "ucs2", [len(c.encode("utf-16-le")) // 2 for c in body]
    chars = sum(widths)
    single, part = LIMITS[encoding]
    if chars <= single:
        return encoding, int(chars > 0), chars
    segments, room = 1, part
    for w in widths:
        if w > room:
            segments, room = segments + 1, part
        room -= w
    return encoding, segments, chars


class Risk(NamedTuple):
    code: str
    message: str


SHORTENERS = frozenset({"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly",
                        "tiny.cc", "shorturl.at", "rb.gy", "bl.ink", "lnkd.in", "t.ly", "v.gd", "s.id"})
MAX_LINKS = 10


def email_risk(subject: str, html: str, text: str, bulk: bool = False) -> list[Risk]:
    """Cheap checks that catch what spam filters punish. An empty list is not a promise of inbox placement.
    `bulk` is marketing or other one-to-many mail, which must carry an unsubscribe link."""
    risks = []
    if html.strip() and not text.strip():
        risks.append(Risk("missing_text", "Add a plain text version: html-only mail is filtered more often"))
    if bulk and "unsubscribe" not in f"{html} {text}".lower():
        risks.append(Risk("missing_unsubscribe", "Bulk mail needs an unsubscribe link in the body"))
    links = len(re.findall(r"<a\s[^>]*href\s*=", html, re.I)) if html.strip() else len(re.findall(r"https?://", text))
    if links > MAX_LINKS:
        risks.append(Risk("many_links", f"{links} links: more than {MAX_LINKS} looks like spam"))
    letters = [c for c in subject if c.isalpha()]
    if len(letters) >= 4 and all(c.isupper() for c in letters):
        risks.append(Risk("all_caps_subject", "An ALL CAPS subject looks like spam"))
    urls = re.findall(r"https?://[^\s\"'<>)]+", f"{html} {text}")
    hosts = {(urlsplit(u).hostname or "").removeprefix("www.") for u in urls}
    short = sorted(h for h in hosts if any(h == s or h.endswith("." + s) for s in SHORTENERS))
    if short:
        risks.append(Risk("url_shortener", f"Links through {', '.join(short)} are blocked by many filters; "
                                           "use your own domain"))
    return risks
