import * as RDialog from "@radix-ui/react-dialog";
import { ArrowRightLeft, Keyboard, LogOut, Moon, Rows3, Search, SlidersHorizontal, Sun, SquareDashed, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { APPS_NAV, CORE, MY_DAY_NAV, SETTINGS, SETTINGS_NAV, appsOn, enabledApps } from "../lib/nav";
import { fuzzy, rank } from "../lib/fuzzy";
import { workspaceId } from "../lib/api";
import { density, theme, toggleDensity, toggleTheme } from "../lib/prefs";
import { selectWorkspace, signOut, useMe } from "../lib/session";
import { useStore } from "../lib/store";
import { Kbd } from "../ui";

type Cmd = { id: string; group: string; label: string; keywords?: string; icon: LucideIcon; keys?: string[]; run: () => void };
const GROUPS = ["Go to", "Settings", "Actions"];

type Props = { open: boolean; onOpenChange: (o: boolean) => void; onCustomize: () => void; onShortcuts: () => void };

export function CommandPalette({ open, onOpenChange, onCustomize, onShortcuts }: Props) {
  const navigate = useNavigate();
  const dark = useStore(theme) === "dark";
  const compact = useStore(density) === "compact";
  const me = useMe();
  const currentWorkspace = useStore(workspaceId);
  const on = useStore(appsOn);
  const apps = useMemo(() => enabledApps(on), [on]);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const commands = useMemo<Cmd[]>(() => {
    const go = (path: string) => () => navigate(path);
    return [
      ...[MY_DAY_NAV, ...CORE, ...apps, APPS_NAV, SETTINGS_NAV].map((i) => ({
        id: `go-${i.id}`, group: "Go to", label: i.label, icon: i.icon, run: go(i.path), keys: i.gKey ? ["G", i.gKey.toUpperCase()] : undefined,
      })),
      { id: "go-ui", group: "Go to", label: "UI gallery", keywords: "components design system dev", icon: SquareDashed, run: go("/dev/ui") },
      ...SETTINGS.map((s) => ({ id: `set-${s.id}`, group: "Settings", label: s.label, keywords: s.keywords, icon: SETTINGS_NAV.icon, run: go(`/settings/${s.id}`) })),
      { id: "act-theme", group: "Actions", label: dark ? "Switch to light theme" : "Switch to dark theme", keywords: "toggle appearance mode", icon: dark ? Sun : Moon, run: toggleTheme },
      { id: "act-density", group: "Actions", label: compact ? "Use comfortable density" : "Use compact density", keywords: "toggle spacing rows", icon: Rows3, run: toggleDensity },
      { id: "act-sidebar", group: "Actions", label: "Customize sidebar", keywords: "hide reorder navigation", icon: SlidersHorizontal, run: onCustomize },
      { id: "act-keys", group: "Actions", label: "Show keyboard shortcuts", keywords: "help keys", icon: Keyboard, run: onShortcuts },
      ...(me?.workspaces ?? [])
        .filter((w) => w.id !== currentWorkspace)
        .map((w) => ({ id: `ws-${w.id}`, group: "Actions", label: `Switch workspace: ${w.name}`, keywords: "change team account", icon: ArrowRightLeft, run: () => selectWorkspace(w.id) })),
      { id: "act-signout", group: "Actions", label: "Sign out", keywords: "log out logout exit", icon: LogOut, run: () => void signOut() },
    ];
  }, [navigate, dark, compact, me, currentWorkspace, apps, onCustomize, onShortcuts]);

  const results = useMemo(() => {
    const scored = rank(commands, (c) => {
      const a = fuzzy(query, c.label);
      const b = c.keywords ? fuzzy(query, c.keywords) : null;
      return a ?? (b === null ? null : b - 5);
    });
    return GROUPS.flatMap((g) => scored.filter((c) => c.group === g));
  }, [commands, query]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
  }, [open]);
  useEffect(() => setActive(0), [query]);
  useEffect(() => {
    listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const run = (c: Cmd | undefined) => {
    if (!c) return;
    onOpenChange(false);
    setTimeout(c.run, 50); // let the palette release focus first
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (results.length) setActive((a) => (a + (e.key === "ArrowDown" ? 1 : -1) + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(results[active]);
    }
  };

  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="ui-overlay" />
        <RDialog.Content className="ui-modal sh-palette" data-kind="dialog" aria-describedby={undefined}>
          <RDialog.Title className="sr-only">Command palette</RDialog.Title>
          <div className="sh-palette-input">
            <Search size={16} aria-hidden />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Search pages, settings and actions"
              role="combobox"
              aria-label="Search pages, settings and actions"
              aria-expanded
              aria-controls="palette-list"
              aria-activedescendant={results[active] ? `cmd-${results[active].id}` : undefined}
              autoComplete="off"
              spellCheck={false}
            />
            <Kbd>Esc</Kbd>
          </div>
          <div className="sh-palette-list" id="palette-list" role="listbox" ref={listRef}>
            {results.length === 0 && <p className="sh-palette-empty">No matches for "{query}".</p>}
            {GROUPS.map((g) => {
              const items = results.filter((r) => r.group === g);
              if (!items.length) return null;
              return (
                <div key={g} role="group" aria-label={g}>
                  <div className="sh-palette-group" aria-hidden>
                    {g}
                  </div>
                  {items.map((c) => {
                    const idx = results.indexOf(c);
                    return (
                      <div
                        key={c.id}
                        id={`cmd-${c.id}`}
                        role="option"
                        aria-selected={idx === active}
                        className="sh-palette-item"
                        onMouseMove={() => setActive(idx)}
                        onClick={() => run(c)}
                      >
                        <c.icon size={16} aria-hidden />
                        <span>{c.label}</span>
                        {c.keys && (
                          <span className="sh-palette-keys" aria-hidden>
                            {c.keys.map((k) => (
                              <Kbd key={k}>{k}</Kbd>
                            ))}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}
