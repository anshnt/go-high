// Where to go after signing in. `next` comes from the address bar, so it is untrusted: only a
// same-origin relative path is allowed. Anything else (other sites, "//host", "/\host", control
// characters that browsers strip, a loop back into the sign-in screens) falls back.
const SAFE_PATH = /^\/(?![/\\])[^\x00-\x20\x7f\\]*$/;
const AUTH_SCREEN = /^\/(signin|signup|auth)(?![\w-])/;

export function safeNext(next: string | null | undefined, fallback = "/"): string {
  if (!next || !SAFE_PATH.test(next) || AUTH_SCREEN.test(next)) return fallback;
  return next;
}
