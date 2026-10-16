import { api, ApiError, errorText, setUnauthorizedHandler, workspaceId } from "./api";
import { memory, useStore } from "./store";

export type User = { id: string; email: string; name: string; email_verified: boolean; has_password: boolean };
export type Brand = { id: string; name: string };
export type Org = { id: string; name: string; role: "owner" | "admin" | "member"; brands: Brand[] };
export type Workspace = { id: string; name: string; org_id: string; brand_id: string; role: "admin" | "member" | null };
export type Me = { user: User; orgs: Org[]; workspaces: Workspace[] };

/** loading: nobody has asked yet. anon: no session (left = the user chose to sign out). */
export type SessionState =
  | { status: "loading" }
  | { status: "ready"; me: Me }
  | { status: "anon"; left?: boolean }
  | { status: "error"; message: string };

// In memory only: the cookie is the real session, this is just what /api/me last said.
export const session = memory<SessionState>({ status: "loading" });

setUnauthorizedHandler(() => {
  if (session.get().status !== "anon") session.set({ status: "anon" });
});

// The stored workspace may belong to an older sign-in or have been removed: fall back to the first one.
const reconcileWorkspace = (me: Me) => {
  if (!me.workspaces.some((w) => w.id === workspaceId.get())) workspaceId.set(me.workspaces[0]?.id ?? null);
};

let inflight: Promise<void> | null = null;
/** Reads /api/me. Safe to call from several places at once. Never throws; the outcome lands in `session`. */
export function refreshMe(): Promise<void> {
  inflight ??= api
    .get<Me>("/api/me")
    .then((me) => {
      reconcileWorkspace(me);
      session.set({ status: "ready", me });
    })
    .catch((e) => session.set(e instanceof ApiError && e.status === 401 ? { status: "anon" } : { status: "error", message: errorText(e) }))
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

/** First call per page load asks the server; later calls reuse the answer. */
export function ensureMe() {
  if (session.get().status === "loading") void refreshMe();
}

export function retryMe() {
  session.set({ status: "loading" });
  void refreshMe();
}

export function selectWorkspace(id: string) {
  const s = session.get();
  if (s.status === "ready" && s.me.workspaces.some((w) => w.id === id)) workspaceId.set(id);
}

export async function createWorkspace(name: string, brandId: string): Promise<Workspace> {
  const ws = await api.post<Workspace>("/api/workspaces", { name, brand_id: brandId });
  await refreshMe();
  selectWorkspace(ws.id);
  return ws;
}

/** This device is done: signed out, or the server cleared our cookie by revoking this session. */
export function leave() {
  workspaceId.set(null);
  session.set({ status: "anon", left: true });
}

export async function signOut() {
  try {
    await api.post("/api/auth/signout");
  } catch {
    /* already signed out, or the server is unreachable: either way this device is done */
  }
  leave();
}

/** Organizations where the user may create workspaces, each with the brand to put them under.
 * ponytail: /api/me has no brand list, so the brand is read off an existing workspace of the org. */
/** Organizations where the user may create workspaces (owners and admins), each with at least one brand. */
export function creatableOrgs(me: Me): Org[] {
  return me.orgs.filter((org) => org.role !== "member" && org.brands.length > 0);
}

export const useSession = () => useStore(session);
/** The signed-in user's data, or null when not signed in (shell components can assume it is set). */
export const useMe = () => {
  const s = useSession();
  return s.status === "ready" ? s.me : null;
};
