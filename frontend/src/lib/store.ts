import { useSyncExternalStore } from "react";

export type Store<T> = {
  get: () => T;
  set: (next: T) => void;
  subscribe: (fn: () => void) => () => void;
};

// Tiny persisted store. localStorage can be missing or throw (private windows, blocked
// site data), so every access is wrapped and the app still works without it.
export function persisted<T>(key: string, initial: T, parse: (raw: unknown) => T | undefined): Store<T> {
  let value = initial;
  try {
    const raw = localStorage.getItem(key);
    if (raw !== null) value = parse(JSON.parse(raw)) ?? initial;
  } catch {
    /* use initial */
  }
  const subs = new Set<() => void>();
  return {
    get: () => value,
    set(next) {
      value = next;
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* not persisted */
      }
      subs.forEach((fn) => fn());
    },
    subscribe(fn) {
      subs.add(fn);
      return () => subs.delete(fn);
    },
  };
}

export const useStore = <T,>(s: Store<T>) => useSyncExternalStore(s.subscribe, s.get);
