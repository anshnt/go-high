// A small, hand-made workspace so every filter test can name the exact records it expects.
import { createMemoryClient } from "../src/records/memoryClient.ts";
import { schema, TAGS, USERS, type Dataset } from "../src/records/seed.ts";
import type { RecordRow } from "../src/records/types.ts";

export const NOW = Date.parse("2026-10-17T12:00:00Z");

const tag = (id: string) => TAGS.find((t) => t.id === id)!;
const rec = (id: string, object: string, values: Record<string, unknown>, extra: Partial<RecordRow> = {}): RecordRow => ({
  id,
  object,
  display_name: String(values.name),
  values,
  owner_id: null,
  created_at: "2026-01-01T00:00:00.000Z",
  updated_at: "2026-01-01T00:00:00.000Z",
  tags: [],
  ...extra,
});
const usd = (amount: number) => ({ amount, currency: "USD" });

export function dataset(): Dataset {
  const { objects, fields } = schema();
  const records: RecordRow[] = [
    rec("co_1", "company", { name: "Alder Labs", industry: "software", size: "11-50", annual_revenue: usd(500_000_000) }, { owner_id: "u_maya" }),
    rec("co_2", "company", { name: "Cobalt Dental", industry: "healthcare", size: "1-10" }),
    rec("co_3", "company", { name: "Harbor Freight", industry: "logistics", size: "201-1000" }),

    rec(
      "ct_1",
      "contact",
      { name: "Ada Lovelace", email: "ada@alder.example", phone: "+1 415 555 0101", company: "co_1", lifecycle: "customer", source: "web", job_title: "Founder", city: "Austin", lead_score: 90, subscribed: true, last_contacted: "2026-10-10", interests: ["pricing", "support"] },
      { owner_id: "u_maya", created_at: "2026-10-11T09:00:00.000Z", tags: [tag("tag_vip")] },
    ),
    rec(
      "ct_2",
      "contact",
      { name: "Grace Hopper", email: "grace@alder.example", company: "co_1", lifecycle: "lead", source: "referral", lead_score: 40, subscribed: false, last_contacted: "2026-08-01" },
      { owner_id: "u_theo", created_at: "2026-09-20T09:00:00.000Z" },
    ),
    rec("ct_3", "contact", { name: "Alan Turing", phone: "+1 212 555 0102", lifecycle: "prospect", lead_score: 10 }, { created_at: "2026-06-01T09:00:00.000Z", tags: [tag("tag_vip"), tag("tag_partner")] }),
    rec(
      "ct_4",
      "contact",
      { name: "Katherine Johnson", email: "katherine@cobalt.example", company: "co_2", lifecycle: "customer", lead_score: 75, subscribed: true, interests: ["integrations"] },
      { owner_id: "u_maya", created_at: "2026-10-16T13:00:00.000Z" },
    ),
    rec("ct_5", "contact", { name: "Margaret Hamilton", company: "co_3", lifecycle: "former", city: "Boston", lead_score: 0 }, { created_at: "2025-10-01T09:00:00.000Z" }),
    rec("ct_6", "contact", { name: "Linus Torvalds", lifecycle: "lead", source: "ads", job_title: "Founder", lead_score: 55 }, { created_at: "2026-10-17T06:00:00.000Z", tags: [tag("tag_partner")] }),
    rec("ct_7", "contact", { name: "Ada Byron", email: "ada.byron@mail.example", lifecycle: "lead" }, { created_at: "2026-07-01T09:00:00.000Z" }),
    rec("ct_8", "contact", { name: "Édith Piaf" }, { created_at: "2026-02-01T09:00:00.000Z" }),

    rec("dl_1", "deal", { name: "Alder Labs Pro plan", amount: usd(1_200_000), stage: "won", close_date: "2026-09-30", contact: "ct_1", company: "co_1" }),
    rec("dl_2", "deal", { name: "Alder Labs add-on", amount: usd(300_000), stage: "proposal", close_date: "2026-11-15", contact: "ct_2", company: "co_1" }),
    rec("dl_3", "deal", { name: "Cobalt rebuild", amount: { amount: 800_000, currency: "EUR" }, stage: "negotiation", close_date: "2026-10-25", contact: "ct_4", company: "co_2" }),
    rec("dl_4", "deal", { name: "Orphan deal", amount: usd(50_000), stage: "new" }),
  ];
  return { objects, fields, records, tags: TAGS, users: USERS, views: [] };
}

export const makeClient = (ds = dataset()) => createMemoryClient({ dataset: ds, now: () => NOW, me: () => ({ id: "u_me", name: "Test User" }) });

/** ids of the records that match, in the default order. */
export async function ids(client: ReturnType<typeof makeClient>, object: string, filter: unknown, extra: Record<string, unknown> = {}): Promise<string[]> {
  const page = await client.query(object, { filter: filter as never, sort: [{ field: "id", dir: "asc" }], limit: 200, ...extra });
  return page.data.map((r) => r.id);
}
