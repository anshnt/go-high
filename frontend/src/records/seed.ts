// Demo data for the memory client: obviously fictional people and companies (example domains, 555 numbers),
// generated from a fixed seed so every run, test and screenshot sees the same records.
import type { Choice, ColorName, FieldDef, FieldOptions, FieldRules, FieldType, Money, ObjectDef, RecordRow, SavedView, Tag, UserRef } from "./types.ts";

export type Dataset = {
  objects: ObjectDef[];
  fields: Record<string, FieldDef[]>;
  records: RecordRow[];
  tags: Tag[];
  users: UserRef[];
  views: SavedView[];
};

// ---- deterministic random numbers ----

export function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
type Rng = () => number;
const pick = <T>(r: Rng, list: readonly T[]): T => list[Math.floor(r() * list.length)]!;
const weighted = <T>(r: Rng, list: readonly (readonly [T, number])[]): T => {
  const total = list.reduce((n, [, w]) => n + w, 0);
  let x = r() * total;
  for (const [v, w] of list) if ((x -= w) < 0) return v;
  return list[list.length - 1]![0];
};
const between = (r: Rng, lo: number, hi: number) => lo + Math.floor(r() * (hi - lo + 1));

// ---- schema ----

const ch = (id: string, label: string, color?: ColorName, probability?: number): Choice => ({ id, label, color, probability });

export const LIFECYCLE = [ch("lead", "Lead", "blue"), ch("prospect", "Prospect", "amber"), ch("customer", "Customer", "green"), ch("former", "Former", "gray")];
const SOURCE = [ch("web", "Web form", "indigo"), ch("referral", "Referral", "green"), ch("event", "Event", "amber"), ch("ads", "Ads", "pink"), ch("import", "Import", "gray")];
const INTERESTS = [ch("pricing", "Pricing"), ch("onboarding", "Onboarding"), ch("integrations", "Integrations"), ch("support", "Support"), ch("partnerships", "Partnerships")];
const INDUSTRY = [
  ch("software", "Software", "indigo"),
  ch("healthcare", "Healthcare", "teal"),
  ch("retail", "Retail", "pink"),
  ch("logistics", "Logistics", "orange"),
  ch("construction", "Construction", "amber"),
  ch("education", "Education", "blue"),
  ch("hospitality", "Hospitality", "purple"),
  ch("finance", "Finance", "green"),
  ch("manufacturing", "Manufacturing", "gray"),
  ch("media", "Media", "red"),
];
export const LOST_REASONS = [ch("price", "Price"), ch("timing", "Timing"), ch("competitor", "Competitor"), ch("no_decision", "No decision"), ch("other", "Other")];
const SIZE = ["1-10", "11-50", "51-200", "201-1000", "1000+"].map((s) => ch(s, s));
export const STAGES = [
  ch("new", "Lead", "gray", 0.1),
  ch("qualified", "Qualified", "blue", 0.25),
  ch("proposal", "Proposal", "amber", 0.5),
  ch("negotiation", "Negotiation", "orange", 0.8),
  ch("won", "Won", "green", 1),
  ch("lost", "Lost", "red", 0),
];

let order = 0;
const field = (key: string, label: string, type: FieldType, o: { options?: FieldOptions; rules?: FieldRules; system?: boolean; archived?: boolean } = {}): FieldDef => ({
  key,
  label,
  type,
  options: o.options ?? {},
  rules: o.rules ?? {},
  is_system: o.system ?? false,
  position: ++order,
  archived: o.archived ?? false,
});

/** Columns every object has. Owner is editable; the two timestamps are not. */
const columns = (): FieldDef[] => [
  field("owner_id", "Owner", "user", { system: true }),
  field("created_at", "Created", "datetime", { system: true, rules: { read_only: true } }),
  field("updated_at", "Updated", "datetime", { system: true, rules: { read_only: true } }),
];

export function schema(): { objects: ObjectDef[]; fields: Record<string, FieldDef[]> } {
  order = 0;
  const objects: ObjectDef[] = [
    { key: "contact", singular: "Contact", plural: "Contacts", icon: "users", is_system: true, primary_fields: ["name"] },
    { key: "company", singular: "Company", plural: "Companies", icon: "building", is_system: true, primary_fields: ["name"] },
    { key: "deal", singular: "Deal", plural: "Deals", icon: "handshake", is_system: true, primary_fields: ["name"] },
  ];
  const fields: Record<string, FieldDef[]> = {
    contact: [
      field("name", "Name", "text", { system: true, rules: { required: true, max_length: 120 } }),
      field("email", "Email", "email"),
      field("phone", "Phone", "phone"),
      field("company", "Company", "record", { options: { object: "company" } }),
      field("lifecycle", "Lifecycle", "select", { options: { choices: LIFECYCLE } }),
      field("source", "Source", "select", { options: { choices: SOURCE } }),
      field("job_title", "Job title", "text", { rules: { max_length: 80 } }),
      field("city", "City", "text"),
      field("lead_score", "Lead score", "number", { rules: { min: 0, max: 100 } }),
      field("subscribed", "Email subscribed", "boolean"),
      field("last_contacted", "Last contacted", "date"),
      field("interests", "Interests", "multi_select", { options: { choices: INTERESTS } }),
      field("about", "About", "long_text", { rules: { max_length: 2000 } }),
      field("legacy_id", "Legacy id", "text", { archived: true }),
      ...columns(),
    ],
    company: [
      field("name", "Name", "text", { system: true, rules: { required: true, max_length: 120 } }),
      field("website", "Website", "url"),
      field("industry", "Industry", "select", { options: { choices: INDUSTRY } }),
      field("size", "Size", "select", { options: { choices: SIZE } }),
      field("city", "City", "text"),
      field("phone", "Phone", "phone"),
      field("annual_revenue", "Annual revenue", "money", { options: { currency: "USD" }, rules: { min: 0 } }),
      field("contacts", "Contacts", "rollup", { options: { result: "number" } }),
      field("open_value", "Open deal value", "rollup", { options: { result: "money", currency: "USD" } }),
      ...columns(),
    ],
    deal: [
      field("name", "Name", "text", { system: true, rules: { required: true, max_length: 120 } }),
      field("amount", "Amount", "money", { options: { currency: "USD" }, rules: { required: true, min: 0 } }),
      field("stage", "Stage", "stage", { options: { choices: STAGES }, rules: { required: true } }),
      field("close_date", "Close date", "date"),
      field("contact", "Contact", "record", { options: { object: "contact" } }),
      field("company", "Company", "record", { options: { object: "company" } }),
      field("source", "Source", "select", { options: { choices: SOURCE } }),
      field("lost_reason", "Lost reason", "select", { options: { choices: LOST_REASONS } }),
      field("lost_note", "Lost note", "long_text", { rules: { max_length: 2000 } }),
      field("weighted", "Weighted value", "formula", { options: { result: "money" } }),
      ...columns(),
    ],
  };
  return { objects, fields };
}

// ---- names ----

const FIRST = "Aaliyah Abel Amara Anders Anika Arjun Beatriz Bram Camila Carys Dario Dmitri Elio Esme Farid Freya Gianna Hamza Ines Isaac Jonas Kavya Kofi Lena Leif Linnea Mateo Mei Milan Nadia Niall Noor Odalys Oskar Paloma Quentin Rahul Renata Rohan Saoirse Soren Tamsin Tariq Thalia Ugo Valentina Wren Xavi Yara Zainab Zeke Ayesha Bastian Chiara Declan Elif Fabian Greta Idris Jun".split(" ");
const LAST = "Abara Ashdown Bellamy Brandt Calloway Chavan Delacroix Dunmore Eastwood Farrow Galloway Hargrove Ishikawa Jasper Kowalczyk Lindgren Mbeki Navarro Okonkwo Pemberton Quillen Rosario Sandoval Thorne Underhill Vasquez Whitlock Yamada Zielinski Adeyemi Bergstrom Castellanos Dhillon Ekström Fitzgerald Gorski Halvorsen Iyer Janssen Kapoor Lowell Marchetti Nakamura Ostrowski Prescott Rahimi Sorensen Takahashi Uchida Varga Winslow Yilmaz Zamora Abernathy Blackwood Cordero Dalgleish Espinoza Fairweather".split(" ");
const PREFIX = "Alder Brightwater Cobalt Driftwood Evergreen Foxglove Granite Harbor Ironwood Juniper Kestrel Lantern Meridian Nimbus Orchard Pinecrest Quarry Riverbend Saltmarsh Timberline Umber Vantage Willowbrook Yarrow Zephyr Copperfield Highland Marigold Starling Tidewater".split(" ");
const SUFFIX: Record<string, string[]> = {
  software: ["Labs", "Systems", "Cloud"],
  healthcare: ["Dental", "Clinic", "Health"],
  retail: ["Goods", "Market", "Supply"],
  logistics: ["Freight", "Logistics", "Haulage"],
  construction: ["Builders", "Roofing", "Contracting"],
  education: ["Academy", "Learning", "Institute"],
  hospitality: ["Hotels", "Kitchen", "Hospitality"],
  finance: ["Capital", "Advisors", "Partners"],
  manufacturing: ["Works", "Fabrication", "Industries"],
  media: ["Studio", "Media", "Press"],
};
const CITIES = ["Austin", "Denver", "Portland", "Chicago", "Atlanta", "Boston", "Seattle", "Phoenix", "Nashville", "Raleigh", "Toronto", "Dublin", "Leeds", "Lisbon", "Pune", "Singapore", "Sydney", "Rotterdam", "Berlin", "Madrid"];
const TITLES = ["Founder", "Owner", "Operations Manager", "Office Manager", "Marketing Lead", "Head of Growth", "Practice Manager", "Sales Director", "Project Manager", "Finance Manager", "Studio Director", "General Manager", "Customer Success Lead", "IT Manager", "Partnerships Manager"];
const AREA = [212, 303, 312, 415, 512, 617, 702, 713, 206, 404, 503, 602, 615, 919, 305, 214];
const PLANS = ["Growth plan", "Pro plan renewal", "Website rebuild", "Onboarding package", "Annual retainer", "Starter plan", "Automation setup", "Campaign pilot", "Team seats", "Reporting add-on"];
const ABOUT = [
  "Met at a regional trade show; wants a follow-up after the quarter closes.",
  "Asked about pricing for a team of twelve and whether onboarding is included.",
  "Referred by an existing customer. Prefers email over calls.",
  "Currently using spreadsheets; looking to move leads into one place.",
  "Evaluating two other tools this month. Decision maker is the owner.",
];

export const USERS: UserRef[] = [
  { id: "u_maya", name: "Maya Okafor", email: "maya@gohigh.example" },
  { id: "u_theo", name: "Theo Lindqvist", email: "theo@gohigh.example" },
  { id: "u_priya", name: "Priya Raman", email: "priya@gohigh.example" },
  { id: "u_diego", name: "Diego Salazar", email: "diego@gohigh.example" },
  { id: "u_hana", name: "Hana Mizuno", email: "hana@gohigh.example" },
  { id: "u_sam", name: "Sam Whitaker", email: "sam@gohigh.example" },
];

export const TAGS: Tag[] = [
  { id: "tag_vip", name: "VIP", color: "purple" },
  { id: "tag_newsletter", name: "Newsletter", color: "blue" },
  { id: "tag_partner", name: "Partner", color: "teal" },
  { id: "tag_event", name: "Event 2026", color: "amber" },
  { id: "tag_risk", name: "At risk", color: "red" },
  { id: "tag_referral", name: "Referral", color: "green" },
  { id: "tag_priority", name: "Priority", color: "orange" },
  { id: "tag_dnc", name: "Do not call", color: "gray" },
];

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const DAY = 86_400_000;
const money = (amount: number, currency = "USD"): Money => ({ amount, currency });

export type SeedOptions = { anchor: number; contacts?: number; companies?: number; deals?: number; /** a user id that owns about a fifth of the deals, so "my deals" is never empty in the public demo */ mine?: string };

/**
 * `anchor` is "now" for the data: created_at values reach back from it, so "created in the last 30 days" is never empty.
 * The numbers of records are the ones the real list has to cope with: 2,000 contacts, 300 companies, 150 deals.
 */
export function seedDataset({ anchor, contacts = 2000, companies = 300, deals = 150, mine }: SeedOptions): Dataset {
  const r = mulberry32(20261017);
  const { objects, fields } = schema();
  const records: RecordRow[] = [];

  const stamp = () => {
    const age = Math.pow(r(), 1.6) * 420 * DAY;
    const created = anchor - age - between(r, 0, DAY - 1);
    const updated = Math.min(anchor, created + Math.pow(r(), 2.2) * (anchor - created));
    return { created_at: new Date(created).toISOString(), updated_at: new Date(updated).toISOString() };
  };
  const tagsFor = (share: number): Tag[] => {
    if (r() > share) return [];
    const first = pick(r, TAGS);
    return r() < 0.2 ? [first, pick(r, TAGS.filter((t) => t.id !== first.id))] : [first];
  };
  const owner = () => (r() < 0.08 ? null : pick(r, USERS).id);

  // companies first: contacts and deals link to them
  const combos = INDUSTRY.flatMap((i) => PREFIX.flatMap((p) => SUFFIX[i.id]!.map((s) => ({ i, name: `${p} ${s}` }))));
  for (let i = combos.length - 1; i > 0; i--) {
    const j = Math.floor(r() * (i + 1));
    [combos[i], combos[j]] = [combos[j]!, combos[i]!];
  }
  const companyRows: RecordRow[] = combos.slice(0, companies).map((c, n) => {
    const city = pick(r, CITIES);
    return {
      id: `co_${String(n + 1).padStart(4, "0")}`,
      object: "company",
      display_name: c.name,
      values: {
        name: c.name,
        website: `https://${slug(c.name)}.example`,
        industry: c.i.id,
        size: weighted(r, [["1-10", 30], ["11-50", 35], ["51-200", 20], ["201-1000", 10], ["1000+", 5]]),
        city,
        phone: `+1 ${pick(r, AREA)} 555 01${String(between(r, 0, 99)).padStart(2, "0")}`,
        annual_revenue: money(between(r, 2, 900) * 100_000 * 100),
      },
      owner_id: owner(),
      tags: tagsFor(0.15),
      ...stamp(),
    };
  });
  records.push(...companyRows);

  // contacts, mostly employed by a company
  const seen = new Set<string>();
  for (let n = 0; n < contacts; n++) {
    let name = "";
    for (let tries = 0; tries < 6; tries++) {
      name = `${pick(r, FIRST)} ${pick(r, LAST)}`;
      if (!seen.has(name)) break;
    }
    seen.add(name);
    const company = r() < 0.7 ? pick(r, companyRows) : null;
    const handle = slug(name).replace(/-/g, ".");
    const domain = company ? `${slug(company.display_name)}.example` : "mail.example";
    const lifecycle = weighted(r, [["lead", 40], ["prospect", 25], ["customer", 25], ["former", 10]]);
    const interests = INTERESTS.filter(() => r() < 0.18).map((c) => c.id);
    const has = (p: number) => r() < p;
    const values: Record<string, unknown> = { name, lifecycle };
    if (has(0.96)) values.email = `${handle}${n % 7 === 0 ? n : ""}@${domain}`;
    if (has(0.72)) values.phone = `+1 ${pick(r, AREA)} 555 01${String(between(r, 0, 99)).padStart(2, "0")}`;
    if (company) values.company = company.id;
    if (has(0.9)) values.source = pick(r, SOURCE).id;
    if (has(0.75)) values.job_title = pick(r, TITLES);
    if (has(0.8)) values.city = pick(r, CITIES);
    if (has(0.8)) values.lead_score = between(r, 0, 100);
    values.subscribed = has(0.7);
    if (has(0.6)) values.last_contacted = new Date(anchor - between(r, 0, 120) * DAY).toISOString().slice(0, 10);
    if (interests.length) values.interests = interests;
    if (has(0.1)) values.about = pick(r, ABOUT);
    records.push({ id: `ct_${String(n + 1).padStart(4, "0")}`, object: "contact", display_name: name, values, owner_id: owner(), tags: tagsFor(0.28), ...stamp() });
  }

  // deals: linked to a contact and that contact's company when there is one
  const contactRows = records.filter((x) => x.object === "contact");
  for (let n = 0; n < deals; n++) {
    const contact = r() < 0.85 ? pick(r, contactRows) : null;
    const company = contact ? (contact.values.company as string | undefined) : r() < 0.6 ? pick(r, companyRows).id : undefined;
    const companyName = companyRows.find((c) => c.id === company)?.display_name ?? "Walk-in";
    const stage = weighted(r, [["new", 25], ["qualified", 25], ["proposal", 20], ["negotiation", 12], ["won", 12], ["lost", 6]]);
    const closed = stage === "won" || stage === "lost";
    const name = `${companyName} ${pick(r, PLANS)}`;
    const currency = weighted(r, [["USD", 80], ["EUR", 12], ["GBP", 8]]);
    const values: Record<string, unknown> = {
      name,
      amount: money(Math.round(Math.exp(7 + r() * 4.2)) * 100, currency),
      stage,
    };
    if (closed) values.close_date = new Date(anchor - between(r, 1, 120) * DAY).toISOString().slice(0, 10);
    else if (stage !== "new" || r() < 0.7) values.close_date = new Date(anchor + between(r, 3, 90) * DAY).toISOString().slice(0, 10);
    if (stage === "qualified" && n % 4 === 1) delete values.close_date; // the pipeline asks for one before a deal leaves Qualified
    if (stage === "lost") values.lost_reason = LOST_REASONS[n % LOST_REASONS.length]!.id;
    if (contact) values.contact = contact.id;
    if (company) values.company = company;
    if (r() < 0.85) values.source = pick(r, SOURCE).id;
    const who = owner(); // drawn here, in the order it always was, so the data is the same with or without `mine`
    records.push({ id: `dl_${String(n + 1).padStart(4, "0")}`, object: "deal", display_name: name, values, owner_id: mine && n % 5 === 2 ? mine : who, tags: tagsFor(0.2), ...stamp() });
  }

  const views: SavedView[] = [
    {
      id: "v_customers",
      object: "contact",
      name: "Customers",
      filter: { and: [{ field: "lifecycle", op: "is", value: "customer" }] },
      columns: ["name", "email", "company", "lifecycle", "owner_id", "created_at"],
      sort: [{ field: "created_at", dir: "desc" }],
      shared: true,
      owner_id: "u_theo",
    },
    {
      id: "v_new_leads",
      object: "contact",
      name: "New leads this month",
      filter: { and: [{ field: "lifecycle", op: "is", value: "lead" }, { field: "created_at", op: "within_last", value: { days: 30 } }] },
      columns: ["name", "email", "phone", "source", "created_at"],
      sort: [{ field: "created_at", dir: "desc" }],
      shared: false,
      owner_id: null,
    },
    {
      id: "v_software",
      object: "company",
      name: "Software companies",
      filter: { and: [{ field: "industry", op: "is", value: "software" }] },
      columns: ["name", "website", "size", "contacts", "open_value", "owner_id"],
      sort: [{ field: "name", dir: "asc" }],
      shared: true,
      owner_id: "u_priya",
    },
    {
      id: "v_open_deals",
      object: "deal",
      name: "Open deals",
      filter: { and: [{ field: "stage", op: "in", value: ["new", "qualified", "proposal", "negotiation"] }] },
      columns: ["name", "amount", "stage", "close_date", "company", "owner_id"],
      sort: [{ field: "amount", dir: "desc" }],
      shared: true,
      owner_id: "u_maya",
    },
  ];

  return { objects, fields, records, tags: TAGS, users: USERS, views };
}
