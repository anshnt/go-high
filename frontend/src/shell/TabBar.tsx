import { useState } from "react";
import { NavLink, useLocation } from "react-router";
import { Ellipsis, Keyboard, Moon, Sun } from "lucide-react";
import { APPS_NAV, CORE, inArea, MY_DAY_NAV, SETTINGS_NAV } from "../lib/nav";
import { theme, toggleTheme } from "../lib/prefs";
import { useStore } from "../lib/store";
import { Sheet } from "../ui";
import { HealthDot } from "./HealthDot";

const TABS = ["inbox", "contacts", "calendar", "tasks"].map((id) => CORE.find((c) => c.id === id)!);
const MORE = [MY_DAY_NAV, ...CORE.filter((c) => !TABS.includes(c)), APPS_NAV, SETTINGS_NAV];

/** Phone navigation: bottom tabs, with the rest in a bottom sheet. Hidden on desktop by CSS. */
export function TabBar({ onShortcuts }: { onShortcuts: () => void }) {
  const [more, setMore] = useState(false);
  const dark = useStore(theme) === "dark";
  const { pathname } = useLocation();
  // Let the sheet finish closing before opening another overlay.
  const then = (fn: () => void) => () => {
    setMore(false);
    setTimeout(fn, 50);
  };
  return (
    <>
      <nav className="sh-tabbar" aria-label="Main">
        {TABS.map((t) => (
          <NavLink key={t.id} to={t.path} className={`sh-tab${inArea(t, pathname) ? " active" : ""}`}>
            <t.icon size={20} aria-hidden />
            <span>{t.label}</span>
          </NavLink>
        ))}
        <button type="button" className="sh-tab" onClick={() => setMore(true)} aria-haspopup="dialog">
          <Ellipsis size={20} aria-hidden />
          <span>More</span>
        </button>
      </nav>
      <Sheet open={more} onOpenChange={setMore} title="More">
        <ul className="sh-more-list">
          {MORE.map((i) => (
            <li key={i.id}>
              <NavLink to={i.path} className="sh-more-link" onClick={() => setMore(false)}>
                <i.icon size={18} aria-hidden />
                {i.label}
              </NavLink>
            </li>
          ))}
          <li>
            <button type="button" className="sh-more-link" onClick={toggleTheme}>
              {dark ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
              {dark ? "Light theme" : "Dark theme"}
            </button>
          </li>
          <li>
            <button type="button" className="sh-more-link" onClick={then(onShortcuts)}>
              <Keyboard size={18} aria-hidden />
              Keyboard shortcuts
            </button>
          </li>
        </ul>
        <div className="sh-more-status">
          <HealthDot showLabel />
        </div>
      </Sheet>
    </>
  );
}
