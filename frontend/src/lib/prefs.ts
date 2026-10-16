import { persisted, type Store } from "./store";

export type Theme = "light" | "dark";
export type Density = "comfortable" | "compact";

// Light is the default. Only a saved choice changes it; prefers-color-scheme is ignored on purpose.
export const theme: Store<Theme> = persisted<Theme>("gh:theme", "light", (v) => (v === "dark" || v === "light" ? v : undefined));
export const density: Store<Density> = persisted<Density>("gh:density", "comfortable", (v) =>
  v === "compact" || v === "comfortable" ? v : undefined,
);
export const sidebarCollapsed: Store<boolean> = persisted("gh:sidebar-collapsed", false, (v) => (typeof v === "boolean" ? v : undefined));

const apply = () => {
  document.documentElement.dataset.theme = theme.get();
  document.documentElement.dataset.density = density.get();
};
theme.subscribe(apply);
density.subscribe(apply);
apply();

export const toggleTheme = () => theme.set(theme.get() === "dark" ? "light" : "dark");
export const toggleDensity = () => density.set(density.get() === "compact" ? "comfortable" : "compact");
