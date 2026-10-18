"""A fictional CRM for development: `python -m app.records.demo_seed <workspace_id>` fills a workspace with companies,
contacts, deals, tags and links, so a developer can open the real app and see it full. Every name is made up
(example domains, 555 numbers).

It writes through the functions the API uses (`store.create`, `tags.apply`, `associations.link_records`), so validation,
identity columns, events, the contact's company link and the timeline are all the real thing. The only shortcut is the
age: records are created now and then dated up to 14 months back with plain UPDATEs, which no request can do.
The content is the same every run (a fixed random seed); ids and the dates, relative to now, are not.
The records are written as the API's database role, under row level security, like a request. Only the teammates and
the dating use the owner connection it is given, because the API's role may not change events or other users.
ponytail: it refuses a workspace that has records already: seeding twice would double the data and fail on tag names."""
import argparse
import math
import random
import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..db import SessionLocal, scoped
from ..models import OrgMember, Role, User, Workspace, WorkspaceMember
from ..security import Ctx
from ..tenancy import ADMIN_ORG_ROLES, effective_role
from . import associations, store, tags
from .models import AssociationType, Pipeline, Record, Stage
from .schema import Catalog

SEED = 20261017
DAY = timedelta(days=1)
TEAM = [("Maya Okafor", "maya"), ("Theo Lindqvist", "theo"), ("Priya Raman", "priya"), ("Diego Salazar", "diego")]
TAGS = [("VIP", "purple"), ("Newsletter", "blue"), ("Partner", "teal"), ("Event 2026", "amber"), ("At risk", "red"),
        ("Referral", "green"), ("Priority", "orange"), ("Do not call", "gray")]
FIRST = ("Aaliyah Abel Amara Anders Anika Arjun Beatriz Bram Camila Carys Dario Dmitri Elio Esme Farid Freya Gianna "
         "Hamza Ines Isaac Jonas Kavya Kofi Lena Leif Linnea Mateo Mei Milan Nadia Niall Noor Odalys Oskar Paloma "
         "Quentin Rahul Renata Rohan Saoirse Soren Tamsin Tariq Thalia Ugo Valentina Wren Xavi Yara Zainab Zeke Ayesha "
         "Bastian Chiara Declan Elif Fabian Greta Idris Jun").split()
LAST = ("Abara Ashdown Bellamy Brandt Calloway Chavan Delacroix Dunmore Eastwood Farrow Galloway Hargrove Ishikawa "
        "Jasper Kowalczyk Lindgren Mbeki Navarro Okonkwo Pemberton Quillen Rosario Sandoval Thorne Underhill Vasquez "
        "Whitlock Yamada Zielinski Adeyemi Bergstrom Castellanos Dhillon Fitzgerald Gorski Halvorsen Iyer Janssen "
        "Kapoor Lowell Marchetti Nakamura Ostrowski Prescott Rahimi Sorensen Takahashi Uchida Varga Winslow Yilmaz "
        "Zamora Abernathy Blackwood Cordero Dalgleish Espinoza Fairweather").split()
PREFIX = ("Alder Brightwater Cobalt Driftwood Evergreen Foxglove Granite Harbor Ironwood Juniper Kestrel Lantern "
          "Meridian Nimbus Orchard Pinecrest Quarry Riverbend Saltmarsh Timberline Umber Vantage Willowbrook Yarrow "
          "Zephyr Copperfield Highland Marigold Starling Tidewater").split()
INDUSTRIES = {
    "Software": ["Labs", "Systems", "Cloud"], "Healthcare": ["Dental", "Clinic", "Health"],
    "Retail": ["Goods", "Market", "Supply"], "Logistics": ["Freight", "Logistics", "Haulage"],
    "Construction": ["Builders", "Roofing", "Contracting"], "Education": ["Academy", "Learning", "Institute"],
    "Hospitality": ["Hotels", "Kitchen", "Hospitality"], "Finance": ["Capital", "Advisors", "Partners"],
    "Manufacturing": ["Works", "Fabrication", "Industries"], "Media": ["Studio", "Media", "Press"]}
PLANS = ["Growth plan", "Pro plan renewal", "Website rebuild", "Onboarding package", "Annual retainer", "Starter plan",
         "Automation setup", "Campaign pilot", "Team seats", "Reporting add-on"]
AREAS = [212, 303, 312, 415, 512, 617, 702, 713, 206, 404, 503, 602, 615, 919, 305, 214]
SIZES = [("1-10", 30), ("11-50", 35), ("51-200", 20), ("201-1000", 10), ("1000_plus", 5)]
LIFECYCLES = [("lead", 40), ("qualified", 20), ("customer", 28), ("churned", 7), ("other", 5)]
# the stages of the Sales pipeline every workspace starts with (records.seed.DEFAULT_STAGES), by name
STAGES = [("Lead", 25), ("Qualified", 25), ("Proposal", 20), ("Negotiation", 12), ("Won", 12), ("Lost", 6)]
LOST_REASONS = ["price", "timing", "competitor", "no_decision", "other"]


def slug(text_: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text_.lower()).strip("-")


def phone(r: random.Random) -> str:
    return f"+1 {r.choice(AREAS)} 555 01{r.randint(0, 99):02d}"


def teammates(db: Session, ws: Workspace) -> None:
    """The fictional team, as members of this workspace with the organization's Member role (people are global,
    memberships are not)."""
    member = db.scalar(select(Role.id).where(Role.org_id == ws.org_id, Role.key == "member"))
    for name, handle in TEAM:
        email = f"{handle}@gohigh.example"
        user_id = db.scalar(select(User.id).where(User.email == email))
        if user_id is None:
            user_id = db.scalar(pg_insert(User).values(email=email, name=name).returning(User.id))
        db.execute(pg_insert(OrgMember).values(user_id=user_id, org_id=ws.org_id, role_id=member)
                   .on_conflict_do_nothing())
        db.execute(pg_insert(WorkspaceMember).values(user_id=user_id, workspace_id=ws.id, role_id=member)
                   .on_conflict_do_nothing())


def people_of(db: Session, ws: Workspace) -> list[uuid.UUID]:
    """Who can act in the workspace, oldest account first: its members and the owners and admins of its organization."""
    admins = select(OrgMember.user_id).join(Role, Role.id == OrgMember.role_id).where(
        OrgMember.org_id == ws.org_id, Role.key.in_(ADMIN_ORG_ROLES))
    members = select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == ws.id)
    everyone = members.union(admins)
    return list(db.scalars(select(User.id).where(User.id.in_(everyone)).order_by(User.created_at, User.id)))


def seed(db: Session, workspace_id: uuid.UUID, *, contacts: int = 1000, companies: int = 150, deals: int = 80) -> dict:
    """Fills the workspace and commits; returns how many of everything it made."""
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise SystemExit(f"There is no workspace {workspace_id}")
    if db.scalar(select(func.count()).select_from(Record).where(Record.workspace_id == ws.id)):
        raise SystemExit("This workspace has records already; seed an empty one")
    teammates(db, ws)
    people = people_of(db, ws)
    admin = db.scalar(select(OrgMember.user_id).join(Role, Role.id == OrgMember.role_id).where(
        OrgMember.org_id == ws.org_id, Role.key.in_(ADMIN_ORG_ROLES))
        .order_by(OrgMember.created_at, OrgMember.user_id).limit(1)) or people[0]
    db.commit()  # the writes below use another connection, which must see the teammates
    with scoped(user_id=admin, org_id=ws.org_id, workspace_id=ws.id) as app:
        done, born = fill(app, people, admin, contacts, companies, deals)
        app.commit()
    # age: dates only a seed may set. The `created` events and company links are dated with their records.
    db.execute(text("UPDATE records SET created_at = :created, updated_at = :updated WHERE id = :id"),
               [{"id": i, "created": created, "updated": updated} for i, (created, updated) in born.items()])
    db.execute(text("UPDATE events SET occurred_at = r.created_at FROM records r WHERE events.workspace_id = :w "
                    "AND events.type = 'record.created' AND events.subject_id = r.id"), {"w": ws.id})
    db.execute(text("UPDATE events SET occurred_at = r.created_at FROM records r WHERE events.workspace_id = :w "
                    "AND events.type = 'association.created' AND r.id = (events.data ->> 'from_record_id')::uuid"),
               {"w": ws.id})
    db.commit()
    return done


def fill(app: Session, people: list[uuid.UUID], actor: uuid.UUID, contacts: int, companies: int, deals: int):
    """The writes, through a session scoped like a request's. Returns the counts and each record's dates."""
    r, now = random.Random(SEED), datetime.now(UTC)
    ws = app.get(Workspace, app.info["scope"]["workspace_id"])
    role, implicit = effective_role(app, actor, ws)  # the seeding person acts with their own role, like a request
    c = Ctx(app, actor, uuid.uuid4(), "", ws, "admin" if implicit else role.key, role, implicit)
    cat = Catalog(c)
    contact, company, deal = (cat.need(k) for k in ("contact", "company", "deal"))

    def owner() -> uuid.UUID | None:
        return None if r.random() < 0.08 else r.choice(people)

    def weighted(items) -> str:
        return r.choices([i for i, _ in items], [w for _, w in items])[0]

    born: dict[uuid.UUID, tuple[datetime, datetime]] = {}  # record id -> (created, updated)

    def make(obj, values: dict) -> Record:
        rec = store.create(cat, obj, values, owner())
        created = now - DAY * (r.random() ** 1.6 * 420) - timedelta(seconds=r.randint(0, 86399))
        born[rec.id] = (created, created + (now - created) * r.random() ** 2.2)
        return rec

    combos = [(industry, f"{p} {s}") for industry, suffixes in INDUSTRIES.items() for p in PREFIX for s in suffixes]
    r.shuffle(combos)
    firms = []
    for industry, name in combos[:companies]:
        firms.append(make(company, {"name": name, "domain": f"{slug(name)}.example", "industry": industry,
                                    "size": weighted(SIZES)}))

    people_made, seen = [], set()
    for n in range(contacts):
        for _ in range(8):
            first, last = r.choice(FIRST), r.choice(LAST)
            if (first, last) not in seen:
                break
        seen.add((first, last))
        firm = r.choice(firms) if firms and r.random() < 0.7 else None
        values = {"first_name": first, "last_name": last, "lifecycle": weighted(LIFECYCLES)}
        if r.random() < 0.96:
            domain = firm.values["domain"] if firm else "mail.example"
            values["email"] = f"{first}.{last}{n if n % 7 == 0 else ''}@{domain}".lower()
        if r.random() < 0.72:
            values["phone"] = phone(r)
        if firm:
            values["company"] = str(firm.id)  # the write also links the contact to the company ("works at")
        people_made.append(make(contact, values))

    pipeline = app.scalar(select(Pipeline).where(Pipeline.object_key == "deal", Pipeline.archived_at.is_(None))
                          .order_by(Pipeline.position, Pipeline.created_at, Pipeline.id))
    stage_ids = {st.name: str(st.id) for st in app.scalars(select(Stage).where(Stage.pipeline_id == pipeline.id))}

    def deal_link(other) -> AssociationType:
        return cat.db.scalars(select(AssociationType).where(
            AssociationType.from_object_id == deal.id, AssociationType.to_object_id == other.id)).first()

    to_contact, to_company = deal_link(contact), deal_link(company)
    firm_by_id = {f.id: f for f in firms}
    made_deals = []
    for _ in range(deals):
        buyer = r.choice(people_made) if people_made and r.random() < 0.85 else None
        firm = firm_by_id.get(uuid.UUID(buyer.values["company"])) if buyer and "company" in buyer.values else None
        firm = firm or (r.choice(firms) if firms and r.random() < 0.6 else None)
        stage = weighted(STAGES)
        values = {"name": f"{firm.display_name if firm else 'Walk-in'} {r.choice(PLANS)}", "stage": stage_ids[stage],
                  "amount": {"amount": round(math.exp(7 + r.random() * 4.2)) * 100,
                             "currency": r.choices(["USD", "EUR", "GBP"], [80, 12, 8])[0]}}
        if stage in ("Won", "Lost"):
            values["close_date"] = (now - DAY * r.randint(1, 120)).date().isoformat()
        if stage == "Lost":
            values["lost_reason"] = r.choice(LOST_REASONS)  # a lost stage asks why
        elif stage not in ("Won", "Lead") or (stage == "Lead" and r.random() < 0.7):
            values["close_date"] = (now + DAY * r.randint(3, 90)).date().isoformat()
        rec = make(deal, values)
        made_deals.append(rec)
        if buyer:
            associations.link_records(c, to_contact, rec, buyer)
        if firm:
            associations.link_records(c, to_company, rec, firm)

    everyone = [*firms, *people_made, *made_deals]
    for name, color in TAGS:
        tag = tags.new_tag(c, tags.NewTag(name=name, color=color))
        # each tag lands on a random slice, so about a third of the contacts carry one and a few carry two
        share = {contact.id: 0.35, company.id: 0.2, deal.id: 0.25}
        hit = [rec.id for rec in everyone if r.random() < share[rec.object_id] / len(TAGS) * 1.2]
        if hit:
            tags.apply(cat, hit, [tag.id], [])

    return {"companies": len(firms), "contacts": len(people_made), "deals": len(made_deals), "tags": len(TAGS)}, born


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fill a workspace with a fictional CRM for development.")
    parser.add_argument("workspace_id", type=uuid.UUID)
    parser.add_argument("--contacts", type=int, default=1000)
    parser.add_argument("--companies", type=int, default=150)
    parser.add_argument("--deals", type=int, default=80)
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        done = seed(db, args.workspace_id, contacts=args.contacts, companies=args.companies, deals=args.deals)
    print("Seeded: " + ", ".join(f"{n} {kind}" for kind, n in done.items()))


if __name__ == "__main__":
    main()
