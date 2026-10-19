import { useCallback, useState } from "react";
import { Outlet } from "react-router";
import { workspaceId } from "../lib/api";
import { useLoadCapabilities } from "../lib/capabilities";
import { useInboxBadge } from "../lib/inboxBadge";
import { useStore } from "../lib/store";
import { CommandPalette } from "./CommandPalette";
import { CustomizeSidebar } from "./CustomizeSidebar";
import { ShortcutSheet } from "./ShortcutSheet";
import { Sidebar } from "./Sidebar";
import { TabBar } from "./TabBar";
import { TopBar } from "./TopBar";
import { useShortcuts } from "./useShortcuts";

export function Shell() {
  const [palette, setPalette] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);
  const [customize, setCustomize] = useState(false);
  const workspace = useStore(workspaceId);
  useLoadCapabilities();
  useInboxBadge();

  const openPalette = useCallback(() => setPalette(true), []);
  const openShortcuts = useCallback(() => setShortcuts(true), []);
  const openCustomize = useCallback(() => setCustomize(true), []);
  // Ctrl/Cmd+K toggles the palette, but never stacks it on top of another dialog.
  const togglePalette = useCallback(() => setPalette((open) => (open ? false : !document.querySelector('[role="dialog"]'))), []);

  useShortcuts({ togglePalette, openShortcuts });

  return (
    <div className="sh-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <Sidebar />
      <div className="sh-main">
        {import.meta.env.VITE_DEMO === "1" && (
          <p className="sh-demo-banner">Demo with fictional data. Changes stay in this tab until you reload.</p>
        )}
        <TopBar onSearch={openPalette} onCustomize={openCustomize} onShortcuts={openShortcuts} />
        <main id="main" className="sh-content" tabIndex={-1}>
          {/* Keyed by workspace: switching remounts the page, so nothing from the old workspace stays on screen. */}
          <Outlet key={workspace ?? "none"} />
        </main>
      </div>
      <TabBar onShortcuts={openShortcuts} />
      <CommandPalette open={palette} onOpenChange={setPalette} onCustomize={openCustomize} onShortcuts={openShortcuts} />
      <ShortcutSheet open={shortcuts} onOpenChange={setShortcuts} />
      <CustomizeSidebar open={customize} onOpenChange={setCustomize} />
    </div>
  );
}
