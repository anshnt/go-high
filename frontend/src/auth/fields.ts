// Same shape the API accepts, so a bad value is caught before the round trip.
export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
export const MIN_PASSWORD = 10;

// Focusing a field on load is a gain with a keyboard and a nuisance on a phone (the keyboard covers the card).
export const FOCUS_FIRST = typeof matchMedia === "function" && matchMedia("(pointer: fine)").matches;

export const emailError = (email: string) => (EMAIL_RE.test(email.trim()) ? undefined : "Enter a valid email address.");

export function passwordHint(password: string) {
  const left = MIN_PASSWORD - password.length;
  if (left <= 0) return "Long enough.";
  return left === MIN_PASSWORD ? `At least ${MIN_PASSWORD} characters.` : `${left} more character${left === 1 ? "" : "s"} to go.`;
}
