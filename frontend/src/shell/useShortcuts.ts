import { useEffect } from "react";
import { useNavigate } from "react-router";
import { CORE, MY_DAY_NAV } from "../lib/nav";

export const TYPING = 'input, textarea, select, [contenteditable], [role="menu"], [role="listbox"], [role="combobox"]';

/** Ctrl/Cmd+K, `?` and Linear-style `g` then a letter. Single keys never fire while typing or inside a dialog. */
export function useShortcuts({ togglePalette, openShortcuts }: { togglePalette: () => void; openShortcuts: () => void }) {
  const navigate = useNavigate();
  useEffect(() => {
    let gAt = 0;
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        togglePalette();
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if ((e.target as HTMLElement).closest(TYPING) || document.querySelector('[role="dialog"]')) return;
      if (e.key === "?") {
        e.preventDefault();
        openShortcuts();
      } else if (gAt && Date.now() - gAt < 1000) {
        gAt = 0;
        const item = [MY_DAY_NAV, ...CORE].find((c) => c.gKey === e.key);
        if (item) {
          e.preventDefault();
          navigate(item.path);
        }
      } else if (e.key === "g") {
        gAt = Date.now();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate, togglePalette, openShortcuts]);
}
