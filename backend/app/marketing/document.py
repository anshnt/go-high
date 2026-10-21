"""The block email format (module 20): a document is a style and a list of blocks, checked by pydantic, and one
renderer turns it into the HTML part and the plain text part of a mail. The builder's preview and every real send use
the same renderer, so what the author sees is what goes out.

The HTML is built for mail clients, not browsers: tables for layout, every style inline as well as in a <style> block,
a fluid 600 px container that becomes full width on a phone (and an MSO ghost table so Outlook keeps it at 600), columns
that stack below 620 px, and a dark scheme declared (`color-scheme`, `prefers-color-scheme` and Outlook.com's
`[data-ogsc]`) with colors chosen for it, so clients that invert colors and clients that honor the scheme both stay
readable. Buttons keep their own colors and a border, images carry alt text and a width.

Merge fields are `{{field_key}}` or `{{field_key|fallback}}` in text, headings, button labels, the subject and the
preheader. A contact's value is escaped like any text and is inserted after the markup is read, so a name with `**` or
`[x](y)` in it cannot add formatting or a link. Link addresses are fixed per campaign (a click token names the link's
number), so they cannot hold merge fields, except `{{unsubscribe_url}}` and `{{preferences_url}}` alone."""
import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_BLOCKS = 100
MAX_DOCUMENT_BYTES = 200_000
WIDTH = 600
MERGE = re.compile(r"\{\{\s*([a-z][a-z0-9_]{0,62})\s*(?:\|\s*([^{}]{0,100}?)\s*)?\}\}")
SYSTEM_URLS = ("unsubscribe_url", "preferences_url")
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Align = Literal["left", "center", "right"]
FONTS = {"sans": "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif",
         "serif": "Georgia,'Times New Roman',Times,serif"}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def check_url(value: str, *, image: bool = False) -> str:
    """http(s) for links (mailto: and tel: too), https for images; or one of the system links alone."""
    value = value.strip()
    if not image and MERGE.fullmatch(value) and MERGE.fullmatch(value).group(1) in SYSTEM_URLS:
        return value
    if MERGE.search(value) or "{{" in value:
        raise ValueError("a link cannot hold merge fields (only {{unsubscribe_url}} or {{preferences_url}} alone)")
    if re.search(r"[\s<>\"']", value):
        raise ValueError("is not a valid address")
    parts = urlsplit(value)
    if not image and parts.scheme in ("mailto", "tel") and parts.path:
        return value
    if parts.scheme not in (("https",) if image else ("http", "https")) or not parts.hostname:
        raise ValueError("must be an https address" if image else "must be an http or https address")
    return value


class Dark(Model):
    background: Color = "#0b0b0e"
    content_background: Color = "#18181b"
    text_color: Color = "#e4e4e7"
    muted_color: Color = "#a1a1aa"
    link_color: Color = "#7aa7ff"


class Style(Model):
    background: Color = "#f4f4f5"
    content_background: Color = "#ffffff"
    text_color: Color = "#18181b"
    muted_color: Color = "#71717a"
    link_color: Color = "#2563eb"
    button_color: Color = "#2563eb"
    button_text_color: Color = "#ffffff"
    font: Literal["sans", "serif"] = "sans"
    dark: Dark = Dark()


BlockId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")]


class Heading(Model):
    type: Literal["heading"]
    id: BlockId | None = None
    text: Annotated[str, Field(min_length=1, max_length=300)]
    level: Literal[1, 2, 3] = 1
    align: Align = "left"


class Text(Model):
    type: Literal["text"]
    id: BlockId | None = None
    text: Annotated[str, Field(min_length=1, max_length=5000)]
    align: Align = "left"

    @field_validator("text")
    @classmethod
    def links_are_valid(cls, value: str) -> str:
        for _, url in LINK.findall(value):
            check_url(url)
        return value


class Button(Model):
    type: Literal["button"]
    id: BlockId | None = None
    label: Annotated[str, Field(min_length=1, max_length=80)]
    url: Annotated[str, Field(max_length=2000)]
    align: Align = "center"

    @field_validator("url")
    @classmethod
    def valid(cls, value: str) -> str:
        return check_url(value)


class Image(Model):
    type: Literal["image"]
    id: BlockId | None = None
    src: Annotated[str, Field(max_length=2000)]
    alt: Annotated[str, Field(max_length=300)] = ""
    href: Annotated[str, Field(max_length=2000)] | None = None
    width: Annotated[int, Field(ge=16, le=WIDTH)] = WIDTH
    align: Align = "center"

    @field_validator("src")
    @classmethod
    def valid_src(cls, value: str) -> str:
        return check_url(value, image=True)

    @field_validator("href")
    @classmethod
    def valid_href(cls, value: str | None) -> str | None:
        return check_url(value) if value else None


class Divider(Model):
    type: Literal["divider"]
    id: BlockId | None = None


class Spacer(Model):
    type: Literal["spacer"]
    id: BlockId | None = None
    height: Annotated[int, Field(ge=4, le=96)] = 24


Inner = Annotated[Heading | Text | Button | Image | Divider | Spacer, Field(discriminator="type")]


class Column(Model):
    blocks: Annotated[list[Inner], Field(max_length=20)] = []


class Columns(Model):
    type: Literal["columns"]
    id: BlockId | None = None
    columns: Annotated[list[Column], Field(min_length=2, max_length=3)]


Block = Annotated[Heading | Text | Button | Image | Divider | Spacer | Columns, Field(discriminator="type")]


class Document(Model):
    version: Literal[1] = 1
    style: Style = Style()
    blocks: Annotated[list[Block], Field(max_length=MAX_BLOCKS)] = []


class Invalid(ValueError):
    """A document, subject or preheader that cannot be saved: `fields` maps a dotted path to what is wrong."""

    def __init__(self, fields: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in fields.items()))
        self.fields = fields


def parse(raw: dict, root: str = "document") -> Document:
    """The checked document; Invalid with dotted paths (`document.blocks.2.url`) otherwise."""
    if len(repr(raw)) > MAX_DOCUMENT_BYTES:
        raise Invalid({root: "is too large"})
    try:
        return Document.model_validate(raw or {})
    except ValidationError as e:
        fields = {}
        for err in e.errors():
            # pydantic names the union member after a list index (blocks.0.button.url): leave that tag out
            raw = err["loc"]
            loc = [str(p) for i, p in enumerate(raw) if not (i and isinstance(raw[i - 1], int) and p in BLOCK_TAGS)]
            fields[".".join([root, *loc])] = err["msg"].removeprefix("Value error, ")
        raise Invalid(fields) from None


BLOCK_TAGS = {"heading", "text", "button", "image", "divider", "spacer", "columns"}


def walk(doc: Document):
    """(path, block) for every block, inside columns too."""
    for i, block in enumerate(doc.blocks):
        yield f"blocks.{i}", block
        if isinstance(block, Columns):
            for c, column in enumerate(block.columns):
                for j, inner in enumerate(column.blocks):
                    yield f"blocks.{i}.columns.{c}.blocks.{j}", inner


def texts(doc: Document):
    """(path, text) of every place a merge field may appear."""
    for path, block in walk(doc):
        if isinstance(block, Heading | Text):
            yield f"{path}.text", block.text
        elif isinstance(block, Button):
            yield f"{path}.label", block.label


def merge_keys(text: str) -> list[str]:
    return [m.group(1) for m in MERGE.finditer(text)]


def check_merge(doc: Document, subject: str, preheader: str, known: set[str], root: str = "document") -> None:
    """Invalid naming every unknown merge field. `known` are the keys the author may use (contact fields they can
    read, and `display_name`)."""
    errors = {}
    places = [("subject", subject), ("preheader", preheader), *((f"{root}.{p}", t) for p, t in texts(doc))]
    for path, text in places:
        unknown = [k for k in merge_keys(text) if k not in known and k not in SYSTEM_URLS]
        if unknown:
            errors[path] = f"unknown merge field {{{{{unknown[0]}}}}}"
        elif "{{" in MERGE.sub("", text):
            errors[path] = "has a merge field that is not written {{field}} or {{field|fallback}}"
    if errors:
        raise Invalid(errors)


def links(doc: Document) -> list[str]:
    """Every distinct link address of the document, in reading order: what a campaign numbers for click tracking.
    mailto:, tel: and the system links are not tracked."""
    found: list[str] = []
    for _, block in walk(doc):
        urls = [block.url] if isinstance(block, Button) else [block.href] if isinstance(block, Image) and block.href \
            else [u for _, u in LINK.findall(block.text)] if isinstance(block, Text) else []
        for url in urls:
            if trackable(url) and url not in found:
                found.append(url)
    return found


def trackable(url: str) -> bool:
    return urlsplit(url).scheme in ("http", "https")


# --- rendering -------------------------------------------------------------------------------------------------

LINK = re.compile(r"\[([^\[\]\n]{1,300})\]\(([^()\s]{1,2000})\)")
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<![\w*])_(.+?)_(?!\w)")
HOLE = "\x00{}\x00"  # where a merge value goes once the markup has been read (NUL cannot come from a saved text)


@dataclass
class Recipient:
    """What a render needs to know about one recipient and one send. The defaults are a preview's."""
    values: dict[str, str] = field(default_factory=dict)  # merge values by key, already formatted as text
    unsubscribe_url: str = "#unsubscribe"
    preferences_url: str = "#preferences"
    link: Callable[[str], str] = lambda url: url  # the tracked address of a link
    open_pixel: str | None = None
    company: str = ""
    address: str = ""


def merged(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """The text with each merge field replaced by a hole, and the values for the holes in order."""
    out: list[str] = []

    def hole(m: re.Match) -> str:
        key, fallback = m.group(1), (m.group(2) or "").strip().strip("\"'")
        out.append(values.get(key) or fallback)
        return HOLE.format(len(out) - 1)
    return MERGE.sub(hole, re.sub("[\x00\x01]", "", text)), out


def fill(rendered: str, holes: list[str], escape: bool = True) -> str:
    return re.sub("\x00(\\d+)\x00", lambda m: html.escape(holes[int(m.group(1))]) if escape
                  else holes[int(m.group(1))], rendered)


def plain(text: str, values: dict[str, str]) -> str:
    """A merged text without markup (the subject, the preheader, a heading)."""
    body, holes = merged(text, values)
    return fill(body, holes, escape=False)


def system_url(url: str, r: Recipient) -> str | None:
    m = MERGE.fullmatch(url)
    if m and m.group(1) in SYSTEM_URLS:
        return r.unsubscribe_url if m.group(1) == "unsubscribe_url" else r.preferences_url
    return None


def href(url: str, r: Recipient) -> str:
    return system_url(url, r) or (r.link(url) if trackable(url) else url)


def with_links(r: Recipient) -> dict[str, str]:
    """Merge values plus the two system links, which may stand alone as a link's address."""
    return {**r.values, "unsubscribe_url": r.unsubscribe_url, "preferences_url": r.preferences_url}


def inline(text: str, r: Recipient, s: Style) -> str:
    """Escaped text with **bold**, _italic_ and [links](https://...), merge values filled in, line breaks kept."""
    body, holes = merged(text, with_links(r))
    body = html.escape(body, quote=True)
    anchors: list[str] = []

    def anchor(m: re.Match) -> str:  # set aside, so emphasis can never reach into an address
        anchors.append(f'<a href="{html.escape(href(html.unescape(m.group(2)), r))}" class="gh-link" '
                       f'style="color:{s.link_color};text-decoration:underline">{m.group(1)}</a>')
        return f"\x01{len(anchors) - 1}\x01"
    body = LINK.sub(anchor, body)
    body = BOLD.sub(r"<strong>\1</strong>", body)
    body = ITALIC.sub(r"<em>\1</em>", body)
    body = re.sub("\x01(\\d+)\x01", lambda m: anchors[int(m.group(1))], body)
    return fill(body, holes)


def text_inline(text: str, r: Recipient) -> str:
    """The plain text form: links as `label (address)`, markup removed."""
    body, holes = merged(text, with_links(r))
    body = LINK.sub(lambda m: f"{m.group(1)} ({href(m.group(2), r)})", body)
    body = BOLD.sub(r"\1", ITALIC.sub(r"\1", body))
    return fill(body, holes, escape=False)


SIZES = {1: (28, 34), 2: (22, 28), 3: (18, 24)}


def block_html(block, r: Recipient, s: Style, font: str, width: int) -> str:
    color = f"color:{s.text_color};font-family:{font}"
    if isinstance(block, Heading):
        size, line = SIZES[block.level]
        return (f'<h{block.level} class="gh-text gh-h{block.level}" style="margin:0;{color};font-size:{size}px;'
                f'line-height:{line}px;font-weight:700;text-align:{block.align}">{inline(block.text, r, s)}'
                f"</h{block.level}>")
    if isinstance(block, Text):
        paragraphs = [p for p in re.split(r"\n\s*\n", block.text.strip()) if p.strip()]
        return "".join(
            f'<p class="gh-text" style="margin:0 0 {12 if i < len(paragraphs) - 1 else 0}px;{color};font-size:16px;'
            f'line-height:24px;text-align:{block.align}">{inline(p, r, s).replace(chr(10), "<br>")}</p>'
            for i, p in enumerate(paragraphs))
    if isinstance(block, Button):
        label = inline(block.label, r, s)
        return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="{block.align}" '
                f'style="margin:0 {"auto" if block.align == "center" else "0"}"><tr>'
                f'<td align="center" bgcolor="{s.button_color}" style="border-radius:6px;background-color:'
                f'{s.button_color};border:1px solid {s.button_color}">'
                f'<a href="{html.escape(href(block.url, r))}" target="_blank" style="display:inline-block;'
                f"padding:12px 24px;font-family:{font};font-size:16px;line-height:20px;font-weight:600;"
                f'color:{s.button_text_color};text-decoration:none;border-radius:6px">{label}</a></td></tr></table>')
    if isinstance(block, Image):
        w = min(block.width, width)
        place = {"center": "margin:0 auto", "right": "margin-left:auto"}.get(block.align, "")
        img = (f'<img src="{html.escape(block.src)}" alt="{html.escape(block.alt)}" width="{w}" '
               f'style="display:block;width:100%;max-width:{w}px;height:auto;border:0;'
               f'{place}">')
        if block.href:
            img = f'<a href="{html.escape(href(block.href, r))}" target="_blank">{img}</a>'
        return img
    if isinstance(block, Divider):
        return (f'<div class="gh-divider" style="border-top:1px solid {s.muted_color};opacity:.35;'
                'height:1px;line-height:1px;font-size:1px">&#8202;</div>')
    if isinstance(block, Spacer):
        return f'<div style="height:{block.height}px;line-height:{block.height}px;font-size:1px">&#8202;</div>'
    if isinstance(block, Columns):
        n = len(block.columns)
        each = (width - 16 * (n - 1)) // n
        cells = []
        for i, column in enumerate(block.columns):
            inner = "".join(f'<div style="padding:0 0 12px">{block_html(b, r, s, font, each)}</div>'
                            for b in column.blocks)
            gap = "" if i == n - 1 else "padding-right:16px;"
            cells.append(f'<!--[if mso]><td width="{each}" valign="top" style="{gap}"><![endif]-->'
                         f'<div class="gh-col" style="display:inline-block;width:100%;max-width:{each}px;'
                         f'vertical-align:top;{gap}box-sizing:border-box">{inner}</div><!--[if mso]></td><![endif]-->')
        return ('<div style="font-size:0;text-align:left"><!--[if mso]><table role="presentation" width="100%"><tr>'
                f'<![endif]-->{"".join(cells)}<!--[if mso]></tr></table><![endif]--></div>')
    raise TypeError(type(block))


def block_text(block, r: Recipient) -> str:
    if isinstance(block, Heading):
        return text_inline(block.text, r)
    if isinstance(block, Text):
        return text_inline(block.text.strip(), r)
    if isinstance(block, Button):
        return f"{text_inline(block.label, r)}: {href(block.url, r)}"
    if isinstance(block, Image):
        alt = block.alt.strip()
        return f"[{alt}]" + (f" ({href(block.href, r)})" if block.href else "") if alt or block.href else ""
    if isinstance(block, Divider):
        return "----"
    if isinstance(block, Columns):
        return "\n\n".join(t for column in block.columns for b in column.blocks if (t := block_text(b, r)))
    return ""


def css(s: Style) -> str:
    d = s.dark
    return (
        ":root{color-scheme:light dark;supported-color-schemes:light dark}"
        "body{margin:0!important;padding:0!important;width:100%!important;-webkit-text-size-adjust:100%;"
        "-ms-text-size-adjust:100%}"
        "table,td{border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt}"
        "img{border:0;outline:none;text-decoration:none;-ms-interpolation-mode:bicubic}"
        f"a{{color:{s.link_color}}}"
        "a[x-apple-data-detectors]{color:inherit!important;text-decoration:none!important}"
        "@media screen and (max-width:620px){.gh-container{width:100%!important;max-width:100%!important}"
        ".gh-pad{padding-left:20px!important;padding-right:20px!important}"
        ".gh-col{display:block!important;max-width:100%!important;width:100%!important;padding-right:0!important}"
        ".gh-h1{font-size:24px!important;line-height:30px!important}}"
        "@media (prefers-color-scheme:dark){"
        f".gh-bg{{background-color:{d.background}!important}}"
        f".gh-card{{background-color:{d.content_background}!important}}"
        f".gh-text{{color:{d.text_color}!important}}"
        f".gh-muted{{color:{d.muted_color}!important}}"
        f".gh-link{{color:{d.link_color}!important}}"
        f".gh-divider{{border-color:{d.muted_color}!important}}}}"
        f"[data-ogsc] .gh-bg{{background-color:{d.background}!important}}"
        f"[data-ogsc] .gh-card{{background-color:{d.content_background}!important}}"
        f"[data-ogsc] .gh-text{{color:{d.text_color}!important}}"
        f"[data-ogsc] .gh-muted{{color:{d.muted_color}!important}}"
        f"[data-ogsc] .gh-link{{color:{d.link_color}!important}}")


@dataclass
class Rendered:
    subject: str
    html: str
    text: str


def render(doc: Document, subject: str, preheader: str, r: Recipient, lang: str = "en") -> Rendered:
    s = doc.style
    font = FONTS[s.font]
    title = html.escape(plain(subject, r.values))
    pre = html.escape(plain(preheader, r.values))
    rows = "".join(
        f'<tr><td class="gh-pad" style="padding:{"0 32px 16px" if i else "32px 32px 16px"}">'
        f"{block_html(b, r, s, font, WIDTH - 64)}</td></tr>" for i, b in enumerate(doc.blocks))
    rows = rows or '<tr><td class="gh-pad" style="padding:32px"></td></tr>'
    muted = f"color:{s.muted_color};font-family:{font};font-size:12px;line-height:18px"
    who = " &middot; ".join(html.escape(x) for x in (r.company, r.address) if x.strip())
    footer = (
        '<tr><td class="gh-pad" style="padding:24px 32px;text-align:center">'
        + (f'<p class="gh-muted" style="margin:0 0 8px;{muted}">{who}</p>' if who else "")
        + f'<p class="gh-muted" style="margin:0;{muted}">'
        f'<a href="{html.escape(r.unsubscribe_url)}" class="gh-link" style="color:{s.muted_color};'
        f'text-decoration:underline">Unsubscribe</a> &middot; '
        f'<a href="{html.escape(r.preferences_url)}" class="gh-link" style="color:{s.muted_color};'
        f'text-decoration:underline">Email preferences</a></p></td></tr>')
    pixel = (f'<img src="{html.escape(r.open_pixel)}" width="1" height="1" alt="" '
             'style="display:block;width:1px;height:1px;border:0;opacity:0">') if r.open_pixel else ""
    # the preheader is followed by invisible spacers, so clients do not pull body text into the inbox preview
    preheader_html = (f'<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;'
                      f'overflow:hidden;mso-hide:all;color:{s.background}">{pre}{"&#847;&zwnj;&nbsp;" * 60}</div>'
                      if pre else "")
    body = (
        "<!DOCTYPE html>"
        f'<html lang="{lang}" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:o="urn:schemas-microsoft-com:office:office"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="X-UA-Compatible" content="IE=edge">'
        '<meta name="x-apple-disable-message-reformatting">'
        '<meta name="format-detection" content="telephone=no,date=no,address=no,email=no,url=no">'
        '<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">'
        f"<title>{title}</title>"
        "<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch>"
        "</o:OfficeDocumentSettings></xml></noscript><![endif]-->"
        f"<style>{css(s)}</style></head>"
        f'<body class="gh-bg" style="margin:0;padding:0;background-color:{s.background};word-spacing:normal">'
        f"{preheader_html}"
        f'<div role="article" aria-roledescription="email" aria-label="{title}" lang="{lang}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="gh-bg" '
        f'style="background-color:{s.background}"><tr><td align="center" style="padding:24px 12px">'
        f'<!--[if mso]><table role="presentation" width="{WIDTH}" align="center" cellpadding="0" cellspacing="0" '
        'border="0"><tr><td><![endif]-->'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="gh-container '
        f'gh-card" style="max-width:{WIDTH}px;width:100%;background-color:{s.content_background};border-radius:8px">'
        f"{rows}</table>"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="gh-container" '
        f'style="max-width:{WIDTH}px;width:100%">{footer}</table>'
        "<!--[if mso]></td></tr></table><![endif]-->"
        f"</td></tr></table></div>{pixel}</body></html>")
    parts = [t for b in doc.blocks if (t := block_text(b, r).strip())]
    tail = [x for x in (r.company, r.address) if x.strip()]
    text = "\n\n".join(parts + ["--", *([" | ".join(tail)] if tail else []),
                                f"Unsubscribe: {r.unsubscribe_url}\nEmail preferences: {r.preferences_url}"])
    return Rendered(plain(subject, r.values).strip(), body, text)


# --- what the deliverability check looks at --------------------------------------------------------------------

@dataclass
class Facts:
    words: int
    images: int
    images_without_alt: int
    link_texts: list[tuple[str, str]]  # (visible text, address) of every link


def facts(doc: Document) -> Facts:
    words, images, no_alt, pairs = 0, 0, 0, []
    for _, block in walk(doc):
        if isinstance(block, Heading | Text):
            visible = LINK.sub(lambda m: m.group(1), block.text)
            words += len(re.findall(r"\w+", MERGE.sub("name", visible)))
            pairs += [(label, url) for label, url in LINK.findall(block.text)]
        elif isinstance(block, Button):
            words += len(re.findall(r"\w+", block.label))
            pairs.append((block.label, block.url))
        elif isinstance(block, Image):
            images += 1
            no_alt += not block.alt.strip()
            if block.href:
                pairs.append((block.alt, block.href))
    return Facts(words, images, no_alt, pairs)
