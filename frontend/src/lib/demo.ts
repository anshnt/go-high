import { ApiError } from "./api";
import { demoCalendars } from "./demoCalendars";
import { demoInbox } from "./demoInbox";
import { DemoMiss, demoTasks } from "./demoTasks";
import type { Me, Workspace } from "./session";

/** Built with VITE_DEMO=1 (the public demo): no backend, fictional data, nothing leaves the browser.
 * The record screens use the in-memory client; this answers the auth, session and workspace calls. */
export const DEMO = import.meta.env.VITE_DEMO === "1";

const ORG = "demo-org";
const BRAND = "demo-brand";
const me: Me = {
  user: { id: "demo-user", email: "alex@acme.example", name: "Alex Rivera", email_verified: true, has_password: true },
  orgs: [{ id: ORG, name: "Acme Agency", role: "owner", brands: [{ id: BRAND, name: "Acme" }] }],
  workspaces: [
    { id: "demo-ws-1", name: "Acme Agency", org_id: ORG, brand_id: BRAND, role: "admin" },
    { id: "demo-ws-2", name: "Harbor Dental", org_id: ORG, brand_id: BRAND, role: "admin" },
  ],
};
let signedIn = true; // visitors land straight in the app; signing out and back in works with any details
const started = new Date().toISOString();

export async function demoRequest<T>(method: string, path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  await new Promise((r) => setTimeout(r, 120)); // feels like a network, keeps loading states honest
  const input = (body ?? {}) as Record<string, string>;
  const route = `${method} ${path.split("?")[0]}`;
  const answer = (value: unknown) => value as T;
  switch (route) {
    case "GET /api/health":
      return answer({ status: "ok", database: true, version: "demo" });
    case "GET /api/me":
      if (!signedIn) throw new ApiError(401, "Sign in required");
      return answer(structuredClone(me));
    case "POST /api/auth/signup":
      me.user = { ...me.user, name: input.name || me.user.name, email: input.email || me.user.email };
      signedIn = true;
      return answer({ user: me.user, org_id: ORG, brand_id: BRAND, workspace_id: me.workspaces[0].id });
    case "POST /api/auth/signin":
    case "POST /api/auth/magic-link/consume":
      signedIn = true;
      return answer({ user: me.user });
    case "POST /api/auth/magic-link":
      return answer({ status: "sent", link: "/auth/magic?token=demo" });
    case "POST /api/auth/signout":
      signedIn = false;
      return answer(undefined);
    case "GET /api/auth/sessions":
      return answer([{ id: "demo-session", created_at: started, last_seen_at: new Date().toISOString(), expires_at: started,
        ip: "203.0.113.7", user_agent: navigator.userAgent, current: true }]);
    case "POST /api/auth/sessions/revoke-others":
      return answer({ revoked: 0 });
    case "POST /api/auth/password":
      return answer(undefined);
    case "GET /api/v1/forms": // ponytail: the forms area shows its empty state in the demo; creating one says it is not available
      return answer({ data: [], next_cursor: null });
    case "GET /api/v1/workflows": // ponytail: like forms, automations show their empty state; creating one says it is not available
      return answer({ data: [], next_cursor: null });
    case "POST /api/workspaces": {
      const ws: Workspace = { id: `demo-ws-${me.workspaces.length + 1}`, name: input.name, org_id: ORG, brand_id: BRAND, role: "admin" };
      me.workspaces.push(ws);
      return answer(ws);
    }
  }
  if (route === "DELETE /api/auth/sessions/demo-session") {
    signedIn = false;
    return answer(undefined);
  }
  try {
    const booked = demoCalendars(method, path, body);
    if (booked !== undefined) return answer(booked); // calendars and bookings: in memory (demoCalendars.ts)
    const mine = demoTasks(method, path, body, { id: me.user.id, name: me.user.name, email: me.user.email });
    if (mine !== undefined) return answer(mine); // tasks, My Day, notifications and people: in memory (demoTasks.ts)
    const messaging = demoInbox(method, path, body, headers, { id: me.user.id, name: me.user.name, email: me.user.email });
    if (messaging !== undefined) return answer(messaging); // inbox, channels, consents, teams, capabilities: in memory (demoInbox.ts)
  } catch (e) {
    if (e instanceof DemoMiss) throw new ApiError(e.status, e.message, undefined, { code: e.code, fields: e.fields });
    throw e;
  }
  throw new ApiError(501, "This is not available in the demo. Run go-high yourself for the full product.");
}
