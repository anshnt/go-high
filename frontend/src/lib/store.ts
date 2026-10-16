import { useSyncExternalStore } from "react";

export type Store<T> = {
  get: () => T;
  set: (next: T) => void;
  subscribe: (fn: () => void) => () => void;
};

// In-memory store for state that must not outlive the tab (who is signed in).
export function memory<T>(initial: T): Store<T> {
  let value = initial;
  const subs = new Set<() => void>();
  return {
    get: () => value,
    set(next) {
      value = next;
      subs.forEach((fn) => fn());
    },
    subscribe(fn) {
      subs.add(fn);
      return () => subs.delete(fn);
    },
  };
}

// Tiny persisted store. localStorage can be missing or throw (private windows, blocked
// site data), so every access is wrapped and the app still works without it.
export function persisted<T>(key: string, initial: T, parse: (raw: unknown) => T | undefined): Store<T> {
  let start = initial;
  try {
    const raw = localStorage.getItem(key);
    if (raw !== null) start = parse(JSON.parse(raw)) ?? initial;
  } catch {
    /* use initial */
  }
  const store = memory(start);
  return {
    ...store,
    set(next) {
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* not persisted */
      }
      store.set(next);
    },
  };
}

export const useStore = <T,>(s: Store<T>) => useSyncExternalStore(s.subscribe, s.get);
