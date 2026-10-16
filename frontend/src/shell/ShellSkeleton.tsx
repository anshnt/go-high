import { sidebarCollapsed } from "../lib/prefs";
import { useStore } from "../lib/store";
import { Skeleton } from "../ui";

/** The shell's outline while the session loads, so the page does not jump when the real shell arrives. */
export function ShellSkeleton() {
  const collapsed = useStore(sidebarCollapsed);
  return (
    <div className="sh-shell" role="status" aria-busy="true">
      <span className="sr-only">Loading your workspace</span>
      <aside className="sh-sidebar" data-collapsed={collapsed || undefined} aria-hidden>
        <div className="sh-brand">
          <span className="sh-mark">g</span>
          <span className="sh-label sh-brand-name">go-high</span>
        </div>
        <div className="sh-skel-nav">
          {[70, 58, 64, 52, 72, 60].map((w, i) => (
            <Skeleton key={i} style={{ width: collapsed ? 20 : `${w}%`, height: 14 }} />
          ))}
        </div>
      </aside>
      <div className="sh-main" aria-hidden>
        <header className="sh-topbar">
          <Skeleton style={{ width: 96, height: 16 }} />
          <div className="sh-skel-search" />
          <div className="sh-topbar-actions">
            <Skeleton style={{ width: 24, height: 24, borderRadius: "50%" }} />
          </div>
        </header>
        <div className="sh-content">
          <div className="sh-page">
            <Skeleton style={{ width: 180, height: 24 }} />
            <div className="sh-skel-rows">
              {[100, 92, 96, 84].map((w, i) => (
                <Skeleton key={i} style={{ width: `${w}%`, height: 44 }} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
