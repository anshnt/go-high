// The transport under lib/api: fetch with the workspace header, the error envelope and 401 handling. No Vite, no
// browser globals at import time, so node can test the clients built on it with a fake fetch.

export class ApiError extends Error {
  status: number;
  /** Seconds from a Retry-After header, when the server sent one (429). */
  retryAfter?: number;
  /** Machine readable code of a /api/v1 error ("validation_failed"). */
  code?: string;
  /** Per-field messages of a /api/v1 validation error, keyed by the server's path ("values.email"). */
  fields?: Record<string, string>;
  constructor(status: number, message: string, retryAfter?: number, extra: { code?: string; fields?: Record<string, string> } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryAfter = retryAfter;
    this.code = extra.code;
    this.fields = extra.fields;
  }
}

const FALLBACK = "Something went wrong. Try again.";

const isFields = (v: unknown): v is Record<string, string> =>
  typeof v === "object" && v !== null && !Array.isArray(v) && Object.values(v).every((x) => typeof x === "string");

// /api/v1 answers {"error": {code, message, fields}}; the older routes {"detail": "text"} (FastAPI also sends
// {"detail": [{...}]} for validation errors).
export async function errorFrom(res: Response): Promise<ApiError> {
  let message = FALLBACK;
  let extra: { code?: string; fields?: Record<string, string> } = {};
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") message = body.detail;
    else if (Array.isArray(body?.detail)) message = "Some details look wrong. Check them and try again.";
    else if (typeof body?.error?.message === "string") {
      message = body.error.message;
      extra = { code: typeof body.error.code === "string" ? body.error.code : undefined, fields: isFields(body.error.fields) ? body.error.fields : undefined };
    }
  } catch {
    /* not JSON: keep the fallback */
  }
  const wait = Number(res.headers.get("Retry-After"));
  return new ApiError(res.status, message, Number.isFinite(wait) && wait > 0 ? wait : undefined, extra);
}

export type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

export type Http = {
  get: <T>(path: string) => Promise<T>;
  post: <T = void>(path: string, body?: unknown) => Promise<T>;
  patch: <T>(path: string, body: unknown) => Promise<T>;
  put: <T>(path: string, body: unknown) => Promise<T>;
  del: (path: string) => Promise<void>;
};

export const httpOf = (send: Send): Http => ({
  get: (path) => send("GET", path),
  post: (path, body) => send("POST", path, body),
  patch: (path, body) => send("PATCH", path, body),
  put: (path, body) => send("PUT", path, body),
  del: (path) => send("DELETE", path),
});

/**
 * A `Send` over fetch. `workspace` is read per call (the user may switch); `unauthorized` hears about every 401
 * so the session store can sign the user out.
 */
export function fetchSend(opts: { workspace: () => string | null; unauthorized?: (path: string) => void; fetch?: typeof fetch }): Send {
  return async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    const ws = opts.workspace();
    if (ws) headers["X-Workspace-Id"] = ws;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res: Response;
    try {
      res = await (opts.fetch ?? fetch)(path, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body) });
    } catch {
      throw new ApiError(0, "Could not reach the server. Check your connection and try again.");
    }
    if (!res.ok) {
      if (res.status === 401) opts.unauthorized?.(path);
      throw await errorFrom(res);
    }
    return (res.status === 204 ? undefined : await res.json()) as T;
  };
}

/** `?a=1&b=x` from a bag of values; undefined, null and empty strings are left out, arrays join with commas. */
export function queryString(params: Record<string, unknown>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, Array.isArray(v) ? v.join(",") : String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}
