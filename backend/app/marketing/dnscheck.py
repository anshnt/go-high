"""Live SPF, DKIM and DMARC checks of a sending domain (module 20): what DNS says now, judged the way receiving mail
servers judge it, with the records to publish and a plain sentence for each problem. `txt` is the only function that
touches the network (tests replace it).

A domain is verified when SPF passes (one record, which includes the provider when one is named and does not end in
+all), DKIM passes (the selector's record holds our public key, or any key in provider mode) and a DMARC record exists.
Gmail and Yahoo require all three of bulk senders since 2024, which is why DMARC is not optional here; `p=none` passes
with a warning. ponytail: the organizational domain for DMARC is taken as the last two labels when the domain has
none of its own, which is wrong for suffixes like co.uk; use the public suffix list when that matters."""
import re
from typing import Literal

import dns.exception
import dns.resolver

from ..channels import dkim

Status = Literal["pass", "warn", "fail", "error"]
TIMEOUT = 3.0  # seconds per server
LIFETIME = 6.0  # seconds for one lookup in all
LOOKUPS = {"include", "a", "mx", "ptr", "exists", "redirect"}  # the SPF terms that cost a DNS lookup


class Unreachable(Exception):
    """DNS did not answer (a timeout, SERVFAIL): the check says so instead of calling the record missing."""


def txt(name: str) -> list[str]:
    """The TXT strings at `name` (each record's strings joined), [] when there are none."""
    resolver = dns.resolver.Resolver()
    resolver.timeout, resolver.lifetime = TIMEOUT, LIFETIME
    try:
        answer = resolver.resolve(name, "TXT")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except (dns.exception.Timeout, dns.resolver.NoNameservers, dns.resolver.NoResolverConfiguration) as e:
        raise Unreachable(f"DNS did not answer for {name}: {type(e).__name__}") from None
    return [b"".join(r.strings).decode("utf-8", "replace") for r in answer]


def result(status: Status, message: str, **more) -> dict:
    return {"status": status, "message": message, **more}


def spf(domain: str, include: str | None) -> dict:
    try:
        found = [t for t in txt(domain) if t.lower().startswith("v=spf1")]
    except Unreachable as e:
        return result("error", str(e), found=[])
    expected = f"v=spf1 include:{include} ~all" if include else "v=spf1 include:<your provider> ~all"
    if not found:
        return result("fail", f"{domain} has no SPF record. Add a TXT record: {expected}", found=[], expected=expected)
    if len(found) > 1:
        return result("fail", "There is more than one SPF record. Receivers treat that as an error: merge them into "
                              "one TXT record.", found=found, expected=expected)
    terms = found[0].lower().split()
    if include and f"include:{include.lower()}" not in terms:
        return result("fail", f"The SPF record does not include {include}, so mail sent through it fails SPF. "
                              f"Add include:{include} before the all.", found=found, expected=expected)
    if "+all" in terms or "all" in terms:
        return result("fail", "The SPF record ends in +all, which lets anyone send as you. Use ~all or -all.",
                      found=found, expected=expected)
    lookups = sum(1 for t in terms if re.split(r"[:/=]", t.lstrip("+-~?"), maxsplit=1)[0] in LOOKUPS)
    if lookups > 10:
        return result("fail", f"The SPF record needs {lookups} DNS lookups; receivers stop at 10 (permerror).",
                      found=found, expected=expected)
    if not any(t.lstrip("+-~?") == "all" or t.startswith("redirect=") for t in terms):
        return result("warn", "The SPF record has no all at the end: add ~all.", found=found, expected=expected)
    return result("pass", "SPF is set up.", found=found, expected=expected)


def dkim_check(domain: str, selector: str, public_key: str | None) -> dict:
    host = f"{selector}._domainkey.{domain}"
    expected = dkim.record(public_key) if public_key else None
    try:
        found = [t for t in txt(host) if "p=" in t]
    except Unreachable as e:
        return result("error", str(e), host=host, found=[], expected=expected)
    if not found:
        what = f"Add a TXT record at {host}" + (" with the value shown." if public_key else
                                               " with the key your provider gives you.")
        return result("fail", f"No DKIM key at {host}. {what}", host=host, found=[], expected=expected)
    keys = [re.sub(r"\s+", "", m.group(1)) for t in found if (m := re.search(r"(?:^|;)\s*p=([^;]*)", t))]
    if public_key and public_key not in keys:
        return result("fail", f"The DKIM key at {host} is not the one shown here: copy the value again, in full.",
                      host=host, found=found, expected=expected)
    if not any(keys):
        return result("fail", f"The DKIM record at {host} has an empty key (p=), which means revoked.",
                      host=host, found=found, expected=expected)
    return result("pass", "DKIM is set up.", host=host, found=found, expected=expected)


def organizational(domain: str) -> str:
    return ".".join(domain.split(".")[-2:])


def dmarc(domain: str) -> dict:
    expected = f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{organizational(domain)}"
    hosts = [f"_dmarc.{domain}"] + ([f"_dmarc.{organizational(domain)}"] if organizational(domain) != domain else [])
    try:
        for host in hosts:
            found = [t for t in txt(host) if t.replace(" ", "").lower().startswith("v=dmarc1")]
            if found:
                break
    except Unreachable as e:
        return result("error", str(e), host=hosts[0], found=[], expected=expected)
    if not found:
        return result("fail", f"No DMARC record. Gmail and Yahoo require one of bulk senders: add a TXT record at "
                              f"_dmarc.{domain}.", host=hosts[0], found=[], expected=expected)
    if len(found) > 1:
        return result("fail", "There is more than one DMARC record; receivers then ignore DMARC. Keep one.",
                      host=host, found=found, expected=expected)
    policy = re.search(r"(?:^|;)\s*p\s*=\s*(\w+)", found[0], re.I)
    if not policy:
        return result("fail", "The DMARC record has no policy (p=).", host=host, found=found, expected=expected)
    if policy.group(1).lower() == "none":
        return result("warn", "DMARC is in monitoring mode (p=none). It passes, but p=quarantine protects your "
                              "domain from spoofing and helps placement.", host=host, found=found, expected=expected)
    return result("pass", f"DMARC is set up (p={policy.group(1).lower()}).", host=host, found=found,
                  expected=expected)


def check(domain: str, selector: str, public_key: str | None, include: str | None) -> dict:
    """The three checks and the verdict: {"spf", "dkim", "dmarc", "verified"}."""
    out = {"spf": spf(domain, include), "dkim": dkim_check(domain, selector, public_key), "dmarc": dmarc(domain)}
    out["verified"] = (out["spf"]["status"] in ("pass", "warn") and out["dkim"]["status"] == "pass"
                       and out["dmarc"]["status"] in ("pass", "warn"))
    return out


def records(domain: str, selector: str, public_key: str | None, include: str | None) -> list[dict]:
    """The DNS records to publish, as a DNS screen asks for them."""
    out = [{"type": "TXT", "host": domain, "value": f"v=spf1 include:{include or '<your provider>'} ~all",
            "purpose": "SPF: which servers may send for the domain (merge with an existing SPF record)"}]
    if public_key:
        out.append({"type": "TXT", "host": f"{selector}._domainkey.{domain}", "value": dkim.record(public_key),
                    "purpose": "DKIM: the key that signs your mail"})
    else:
        out.append({"type": "TXT or CNAME", "host": f"{selector}._domainkey.{domain}",
                    "value": "the DKIM record your provider gives you", "purpose": "DKIM: your provider's signing key"})
    out.append({"type": "TXT", "host": f"_dmarc.{domain}",
                "value": f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{organizational(domain)}",
                "purpose": "DMARC: what receivers do with mail that fails SPF and DKIM"})
    return out
