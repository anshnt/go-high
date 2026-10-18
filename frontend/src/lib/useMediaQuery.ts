import { useSyncExternalStore } from "react";

/** Whether a media query matches now, and again whenever it changes ("(max-width: 639px)" for a phone). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const m = window.matchMedia(query);
      m.addEventListener("change", notify);
      return () => m.removeEventListener("change", notify);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}
