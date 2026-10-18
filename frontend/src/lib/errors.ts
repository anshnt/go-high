import { ApiError, errorText } from "./api";

/**
 * What went wrong, in the validation error's own words when it has them ("A repeating task needs a due date")
 * rather than the general "The task is not valid".
 */
export function whatWentWrong(e: unknown): string {
  const first = e instanceof ApiError && e.fields ? Object.values(e.fields)[0] : undefined;
  return first ? first.charAt(0).toUpperCase() + first.slice(1) : errorText(e);
}
