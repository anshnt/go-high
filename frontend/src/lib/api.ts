import { persisted } from "./store";

/** The workspace every request acts on (sent as X-Workspace-Id). null until /api/me has been read. */
export const workspaceId = persisted<string | null>("gh:workspace", null, (v) => (typeof v === "string" && v ? v : undefined));

export class ApiError extends Error {
  status: number;
  /** Seconds from a Retry-After header, when the server sent one (429). */
  retryAfter?: number;
  constructor(status: number, message: string, retryAfter?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

// A 401 from these is an answer ("wrong password", "link used"), not an expired session.
// /api/auth/sessions is deliberately not listed: it needs a session like any other call.
const PUBLIC_AUTH = /^\/api\/auth\/(signup|signin|signout|magic-link)(\/|$)/;

let onUnauthorized: () => void = () => {};
/** Called once for any 401 from a signed-in call; the session store registers it. */
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn;
};

const FALLBACK = "Something went wrong. Try again.";

// FastAPI answers {"detail": "text"}, or {"detail": [{...}]} for validation errors; other
// services may answer {"error": {"message": "text"}}.
async function errorFrom(res: Response): Promise<ApiError> {
  let message = FALLBACK;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") message = body.detail;
    else if (Array.isArray(body?.detail)) message = "Some details look wrong. Check them and try again.";
    else if (typeof body?.error?.message === "string") message = body.error.message;
  } catch {
    /* not JSON: keep the fallback */
  }
  const wait = Number(res.headers.get("Retry-After"));
  return new ApiError(res.status, message, Number.isFinite(wait) && wait > 0 ? wait : undefined);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  // Constant-folded away in normal builds, so the demo responder never ships with the real app.
  if (import.meta.env.VITE_DEMO === "1") return (await import("./demo")).demoRequest<T>(method, path, body);
  const headers: Record<string, string> = { Accept: "application/json" };
  const ws = workspaceId.get();
  if (ws) headers["X-Workspace-Id"] = ws;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(path, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Could not reach the server. Check your connection and try again.");
  }
  if (!res.ok) {
    if (res.status === 401 && !PUBLIC_AUTH.test(path)) onUnauthorized();
    throw await errorFrom(res);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T = void>(path: string, body?: unknown) => request<T>("POST", path, body),
  del: (path: string) => request<void>("DELETE", path),
};

export const errorText = (e: unknown) => (e instanceof ApiError ? e.message : FALLBACK);
