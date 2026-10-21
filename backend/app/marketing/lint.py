"""What the pre-send deliverability check finds in an email's content (module 20): spam trigger words, a missing
unsubscribe link, the balance of text and images, alt text, the domains links go to (shorteners, bare IPs, plain
http, a link whose text names another site than it goes to) and a size that Gmail clips. An `error` stops a send; a
`warning` is shown and the author decides. Pure functions: campaigns.py adds what needs the database (the domain's
DNS, the audience)."""
import ipaddress
import re
from typing import Literal, NamedTuple
from urllib.parse import urlsplit

from .. import compliance
from . import document

Level = Literal["error", "warning", "info"]
GMAIL_CLIP = 102 * 1024  # Gmail cuts the message off ("[Message clipped]") above this, the footer with it
SUBJECT_MAX = 78  # what most inboxes show before cutting
WORDS_PER_IMAGE = 50  # less text than this per image reads as an image-only mail to filters
SPAM_PHRASES = (
    "100% free", "100% satisfied", "act now", "additional income", "all natural", "apply now", "as seen on",
    "be your own boss", "billion dollars", "buy direct", "buy now", "call now", "cancel at any time", "cash bonus",
    "casino", "cheap meds", "click below", "click here", "congratulations", "dear friend", "double your",
    "earn extra cash", "earn money", "eliminate debt", "extra income", "fast cash", "financial freedom", "free access",
    "free gift", "free money", "free offer", "get paid", "giveaway", "guaranteed", "incredible deal", "instant cash",
    "investment opportunity", "lose weight", "lottery", "lowest price", "make money", "million dollars", "miracle",
    "no catch", "no credit check", "no fees", "no hidden costs", "no obligation", "not spam", "once in a lifetime",
    "order now", "pure profit", "risk-free", "risk free", "satisfaction guaranteed", "this is not spam",
    "this isn't spam", "urgent", "viagra", "while supplies last", "winner", "wire transfer", "work from home",
    "you have been selected", "you're a winner")


class Issue(NamedTuple):
    level: Level
    code: str
    message: str


def phrases(text: str) -> list[str]:
    low = re.sub(r"\s+", " ", text.lower())
    return [p for p in SPAM_PHRASES if re.search(rf"(?<!\w){re.escape(p)}(?!\w)", low)]


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def is_ip(name: str) -> bool:
    try:
        ipaddress.ip_address(name.strip("[]"))
        return True
    except ValueError:
        return False


def looks_like_domain(text: str) -> str | None:
    m = re.search(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", text.lower())
    return m.group(1).removeprefix("www.") if m else None


def content(doc: document.Document, subject: str, out: document.Rendered) -> list[Issue]:
    """The checks of one rendered email (a preview render, whose unsubscribe link is `#unsubscribe`, or a real one)."""
    issues: list[Issue] = []
    if not subject.strip():
        issues.append(Issue("error", "missing_subject", "Add a subject line"))
    elif len(out.subject) > SUBJECT_MAX:
        issues.append(Issue("warning", "long_subject", f"The subject has {len(out.subject)} characters; inboxes show "
                                                       f"about {SUBJECT_MAX}"))
    if re.search(r"[!?]{2,}|\${2,}", subject):
        issues.append(Issue("warning", "subject_punctuation", "Repeated !, ? or $ in the subject looks like spam"))
    if re.match(r"\s*(re|fwd?)\s*:", subject, re.I):
        issues.append(Issue("warning", "fake_reply", "A subject that starts with Re: or Fwd: on a campaign misleads "
                                                     "people and filters"))
    found = phrases(f"{subject} {out.text}")
    if found:
        issues.append(Issue("warning", "spam_words", "Words spam filters weigh against you: "
                                                     + ", ".join(f'"{w}"' for w in found[:8])))
    if not doc.blocks:
        issues.append(Issue("error", "empty", "The email has no content"))
    if "unsubscribe" not in out.html.lower() or "unsubscribe" not in out.text.lower():
        issues.append(Issue("error", "missing_unsubscribe", "Every campaign needs an unsubscribe link"))
    f = document.facts(doc)
    if f.images and f.words == 0:
        issues.append(Issue("warning", "image_only", "The email is only images: filters cannot read it and many "
                                                     "people never load images. Add text"))
    elif f.images and f.words / f.images < WORDS_PER_IMAGE:
        issues.append(Issue("warning", "image_ratio", f"{f.words} words for {f.images} image"
                                                      f"{'s' if f.images > 1 else ''}: aim for at least "
                                                      f"{WORDS_PER_IMAGE} words per image"))
    if f.images_without_alt:
        many = "images have" if f.images_without_alt > 1 else "image has"
        issues.append(Issue("warning", "missing_alt", f"{f.images_without_alt} {many} no alt text: it is what people "
                                                      "see when images are off"))
    domains: list[str] = []
    for label, url in f.link_texts:
        if not document.trackable(url):
            continue
        name = host(url)
        if name and name not in domains:
            domains.append(name)
        if is_ip(name):
            issues.append(Issue("warning", "ip_link", f"A link goes to a bare IP address ({name}): use a domain"))
        if url.startswith("http://"):
            issues.append(Issue("warning", "insecure_link", f"{url[:80]} is not https"))
        shown = looks_like_domain(label)
        if shown and name and shown != name and not name.endswith("." + shown) and not shown.endswith("." + name):
            issues.append(Issue("warning", "mismatched_link", f'The link text names {shown} but it goes to {name}: '
                                                              "filters treat that as phishing"))
    for risk in compliance.email_risk(subject, out.html, out.text, bulk=True):
        if risk.code in ("url_shortener", "many_links"):
            issues.append(Issue("warning", risk.code, risk.message))
    size = len(out.html.encode())
    if size > GMAIL_CLIP:
        issues.append(Issue("warning", "clipped", f"The email is {size // 1024} KB; Gmail clips mail over 102 KB, "
                                                  "footer and unsubscribe link included"))
    if domains:
        issues.append(Issue("info", "link_domains", "Links go to " + ", ".join(domains[:10])))
    return dedupe(issues)


def dedupe(issues: list[Issue]) -> list[Issue]:
    seen, out = set(), []
    for i in issues:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out
