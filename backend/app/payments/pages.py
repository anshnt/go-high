"""The hosted pages of payments (module 21), rendered on the server as small, self-contained HTML: an invoice (which is
also its print view: the browser's Print saves it as a PDF), a payment link's checkout, the page after paying, and the
test provider's card page. No framework and no script but the one-line print button, so they load fast anywhere and
a strict Content-Security-Policy holds. Every value is escaped; amounts are formatted from minor units here only."""
from html import escape

from . import money

CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; img-src 'self' data:; base-uri 'none'; "
       "frame-ancestors 'none'; form-action 'self' https://checkout.stripe.com")
HEADERS = {"Content-Security-Policy": CSP, "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
           "X-Content-Type-Options": "nosniff"}

STYLE = """
:root{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--fg:#14161a;--muted:#5d6470;--line:#e3e6ea;--accent:#4f46e5;
--accent-fg:#fff;--ok:#0f7a3d;--ok-bg:#e6f6ec;--warn:#8a5a00;--warn-bg:#fff4dc;--bad:#b42318;--bad-bg:#fdecea;
--radius:12px;font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a20;--fg:#eceef2;--muted:#a3a9b4;--line:#2a2f38;
--accent:#8b85ff;--accent-fg:#0f1115;--ok:#6fdc9a;--ok-bg:#12301f;--warn:#f5c56b;--warn-bg:#33270f;--bad:#ff8a80;
--bad-bg:#3a1714}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg)}
main{max-width:760px;margin:0 auto;padding:32px 16px 48px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:28px}
h1{font-size:1.5rem;font-weight:600;margin:0 0 4px}h2{font-size:1rem;font-weight:600;margin:24px 0 8px}
.muted{color:var(--muted)}.mono{font-variant-numeric:tabular-nums;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.head{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:flex-start}
.badge{display:inline-block;border-radius:999px;padding:2px 10px;font-size:.8rem;font-weight:600;background:var(--line)}
.badge.ok{background:var(--ok-bg);color:var(--ok)}.badge.warn{background:var(--warn-bg);color:var(--warn)}
.badge.bad{background:var(--bad-bg);color:var(--bad)}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:20px 0}
.meta div span{display:block;font-size:.8rem;color:var(--muted)}
table{width:100%;border-collapse:collapse;margin-top:8px}th,td{padding:10px 6px;border-bottom:1px solid var(--line);
text-align:left;vertical-align:top}th{font-size:.8rem;color:var(--muted);font-weight:600}
td.num,th.num{text-align:right;white-space:nowrap}.totals{margin-left:auto;max-width:320px;margin-top:12px}
.totals div{display:flex;justify-content:space-between;padding:4px 0}.totals .grand{font-weight:700;font-size:1.1rem;
border-top:1px solid var(--line);margin-top:6px;padding-top:10px}
.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:24px}
button,.button{font:inherit;border-radius:10px;padding:10px 18px;border:1px solid var(--line);background:var(--card);
color:var(--fg);cursor:pointer;text-decoration:none;display:inline-block}
button.primary{background:var(--accent);color:var(--accent-fg);border-color:var(--accent);font-weight:600}
button:focus-visible,input:focus-visible,a:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
label{display:block;font-size:.9rem;font-weight:600;margin:14px 0 4px}
input{font:inherit;width:100%;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--card);
color:var(--fg)}input.qty{width:90px}
.alert{border-radius:10px;padding:12px 14px;margin:16px 0;background:var(--bad-bg);color:var(--bad)}
.alert.ok{background:var(--ok-bg);color:var(--ok)}.alert.info{background:var(--line);color:var(--fg)}
.hp{position:absolute;left:-10000px;width:1px;height:1px;overflow:hidden}
.foot{margin-top:24px;font-size:.85rem;color:var(--muted);white-space:pre-line}
@media (max-width:520px){.card{padding:18px}th.hide,td.hide{display:none}}
@media print{body{background:#fff;color:#000}main{padding:0}.card{border:0;padding:0}.actions,.noprint{display:none}}
"""


def page(title: str, body: str, *, script: bool = False) -> str:
    js = '<script src="/pay/print.js" defer></script>' if script else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f"<title>{escape(title)}</title><style>{STYLE}</style>{js}</head><body><main>{body}</main></body></html>")


def amount(value: int, currency: str) -> str:
    return escape(money.format_amount(value, currency))


def notice(text: str, tone: str = "") -> str:
    return f'<div class="alert {tone}" role="{"alert" if not tone else "status"}">{escape(text)}</div>'


def message(title: str, text: str, tone: str = "info", business: str = "") -> str:
    head = f'<p class="muted">{escape(business)}</p>' if business else ""
    return page(title, f'<div class="card">{head}<h1>{escape(title)}</h1>{notice(text, tone)}</div>')


STATUS = {"open": ("Due", "warn"), "paid": ("Paid", "ok"), "void": ("Void", "bad"),
          "uncollectible": ("Uncollectible", "bad"), "draft": ("Draft", "")}


def date(value) -> str:
    return value.strftime("%d %b %Y") if value else "None"


def invoice(inv, lines, settings, contact_name: str | None, *, pay_action: str | None, flash: str | None,
            refunded: int = 0) -> str:
    label, tone = STATUS.get(inv.status, (inv.status, ""))
    cur = inv.currency
    rows = "".join(
        f"<tr><td>{escape(x.description)}"
        + (f'<div class="muted">{escape(x.tax_name)} {x.tax_bp / 100:g}%{" incl." if x.tax_inclusive else ""}</div>'
           if x.tax_name else "")
        + f'</td><td class="num mono hide">{x.quantity}</td><td class="num mono hide">'
        + (amount(x.unit_amount, cur) if x.unit_amount * x.quantity == x.amount
           else ("Prorated" if x.proration else "Tiered"))
        + f'</td><td class="num mono">{amount(x.amount, cur)}</td></tr>' for x in lines)
    taxes: dict[str, int] = {}
    for x in lines:
        if x.tax:
            key = f"{x.tax_name} ({x.tax_bp / 100:g}%{', included' if x.tax_inclusive else ''})"
            taxes[key] = taxes.get(key, 0) + x.tax
    totals = [("Subtotal", inv.subtotal)]
    if inv.discount:
        totals.append(("Discount", -inv.discount))
    totals += list(taxes.items())
    if inv.credit_applied:
        totals.append(("Credit applied", -inv.credit_applied))
    sums = "".join(f'<div><span>{escape(k)}</span><span class="mono">{amount(v, cur)}</span></div>' for k, v in totals)
    sums += f'<div class="grand"><span>Total</span><span class="mono">{amount(inv.total, cur)}</span></div>'
    if inv.amount_paid:
        sums += f'<div><span>Paid</span><span class="mono">{amount(-inv.amount_paid, cur)}</span></div>'
    due = max(inv.total - inv.amount_paid, 0) if inv.status == "open" else 0
    if inv.status == "open":
        sums += f'<div class="grand"><span>Amount due</span><span class="mono">{amount(due, cur)}</span></div>'
    if refunded:
        sums += f'<div><span>Refunded</span><span class="mono">{amount(refunded, cur)}</span></div>'
    title = f"Invoice {inv.number}" if inv.number else "Receipt"
    business = escape(settings.business_name or "")
    details = escape(settings.business_details or "")
    pay = (f'<form method="post" action="{escape(pay_action)}"><button class="primary" type="submit">'
           f"Pay {amount(due, cur)}</button></form>") if pay_action and due else ""
    body = f"""<div class="card"><div class="head"><div><p class="muted" style="margin:0">{business}</p>
<h1>{escape(title)}</h1><span class="badge {tone}">{escape(label)}</span></div>
<div class="muted" style="white-space:pre-line;text-align:right">{details}</div></div>
{flash or ""}
<div class="meta"><div><span>Billed to</span>{escape(contact_name or "Customer")}</div>
<div><span>Issued</span>{date(inv.issued_at)}</div><div><span>Due</span>{date(inv.due_at)}</div>
{f'<div><span>Paid</span>{date(inv.paid_at)}</div>' if inv.paid_at else ""}</div>
<table><caption class="hp">Items</caption><thead><tr><th scope="col">Description</th>
<th scope="col" class="num hide">Qty</th><th scope="col" class="num hide">Unit price</th>
<th scope="col" class="num">Amount</th></tr></thead><tbody>{rows}</tbody></table>
<div class="totals">{sums}</div>
{f'<p class="foot">{escape(inv.memo)}</p>' if inv.memo else ""}
<div class="actions">{pay}<button type="button" data-print>Print or save as PDF</button></div>
{f'<p class="foot">{escape(inv.footer)}</p>' if inv.footer else ""}</div>"""
    return page(f"{title} - {settings.business_name or 'Invoice'}", body, script=True)


def link_page(link, items, business: str, *, action: str, error: str | None = None, values: dict | None = None,
              available: bool = True) -> str:
    """`items`: (index, price, description, unit text, quantity, adjustable, min, max)."""
    v = values or {}
    rows = ""
    for i, _price, description, unit, quantity, adjustable, low, high in items:
        qty = (f'<label for="qty_{i}" class="hp">Quantity of {escape(description)}</label>'
               f'<input class="qty mono" id="qty_{i}" name="qty_{i}" type="number" inputmode="numeric" '
               f'min="{low}" max="{high}" value="{escape(str(v.get(f"qty_{i}", quantity)))}">') if adjustable \
            else f'<span class="mono">{quantity}</span>'
        rows += (f'<tr><td>{escape(description)}</td><td class="num">{qty}</td>'
                 f'<td class="num mono">{escape(unit)}</td></tr>')
    coupon = (f'<label for="coupon">Discount code <span class="muted">(optional)</span></label>'
              f'<input id="coupon" name="coupon" autocomplete="off" value="{escape(v.get("coupon", ""))}">'
              if link.allow_coupons else "")
    phone = (f'<label for="phone">Phone</label><input id="phone" name="phone" type="tel" autocomplete="tel" '
             f'value="{escape(v.get("phone", ""))}">' if link.collect_phone else "")
    form = f"""<form method="post" action="{escape(action)}" novalidate>
<table><caption class="hp">What you are buying</caption><thead><tr><th scope="col">Item</th>
<th scope="col" class="num">Qty</th><th scope="col" class="num">Price</th></tr></thead><tbody>{rows}</tbody></table>
<label for="name">Name</label><input id="name" name="name" autocomplete="name" required
 value="{escape(v.get("name", ""))}">
<label for="email">Email</label><input id="email" name="email" type="email" autocomplete="email" required
 value="{escape(v.get("email", ""))}">{phone}{coupon}
<div class="hp" aria-hidden="true"><label for="website">Website</label>
<input id="website" name="website" tabindex="-1" autocomplete="off"></div>
<div class="actions"><button class="primary" type="submit">Continue to payment</button></div>
<p class="muted" style="font-size:.85rem">Taxes and discounts are worked out on the next step, before you pay.</p>
</form>""" if available else notice("This page cannot take payments right now. Please try again later.")
    body = (f'<div class="card"><p class="muted" style="margin:0">{escape(business)}</p><h1>{escape(link.name)}</h1>'
            f'{notice(error) if error else ""}{form}</div>')
    return page(link.name, body)


def fake_checkout(description: str, total: str, action: str, cancel: str) -> str:
    body = f"""<div class="card"><p class="muted" style="margin:0">Test provider: no real money moves</p>
<h1>{escape(description)}</h1><p class="mono" style="font-size:1.4rem">{escape(total)}</p>
{notice("This is the development payment provider. Use Pay to succeed or Decline to fail.", "info")}
<form method="post" action="{escape(action)}"><div class="actions">
<button class="primary" type="submit" name="outcome" value="succeeded">Pay</button>
<button type="submit" name="outcome" value="failed">Decline</button>
<a class="button" href="{escape(cancel)}">Cancel</a></div></form></div>"""
    return page("Test checkout", body)


PRINT_JS = ("document.addEventListener('click',function(e){var b=e.target.closest('[data-print]');"
            "if(b){e.preventDefault();window.print();}});")
