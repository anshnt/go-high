import { ApiError, fetchSend, httpOf, queryString } from "./http";
import { persisted } from "./store";

export { ApiError, queryString };

/** The workspace every request acts on (sent as X-Workspace-Id). null until /api/me has been read. */
export const workspaceId = persisted<string | null>("gh:workspace", null, (v) => (typeof v === "string" && v ? v : undefined));

// A 401 from these is an answer ("wrong password", "link used"), not an expired session.
// /api/auth/sessions is deliberately not listed: it needs a session like any other call.
const PUBLIC_AUTH = /^\/api\/auth\/(signup|signin|signout|magic-link)(\/|$)/;

let onUnauthorized: () => void = () => {};
/** Called once for any 401 from a signed-in call; the session store registers it. */
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn;
};

const FALLBACK = "Something went wrong. Try again.";

const live = fetchSend({
  workspace: () => workspaceId.get(),
  unauthorized: (path) => {
    if (!PUBLIC_AUTH.test(path)) onUnauthorized();
  },
});

async function request<T>(method: string, path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  // Constant-folded away in normal builds, so the demo responder never ships with the real app.
  if (import.meta.env.VITE_DEMO === "1") return (await import("./demo")).demoRequest<T>(method, path, body, headers);
  return live<T>(method, path, body, headers);
}

export const api = httpOf(request);

export const errorText = (e: unknown) => (e instanceof ApiError ? e.message : FALLBACK);
