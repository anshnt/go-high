import { NavLink, useLocation } from "react-router";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { APPS_NAV, appsOn, enabledApps, inArea, MY_DAY_NAV, SETTINGS_NAV, sidebarPrefs, visibleCore, type NavItem } from "../lib/nav";
import { sidebarCollapsed } from "../lib/prefs";
import { useStore } from "../lib/store";
import { Button, Tooltip } from "../ui";
import { HealthDot } from "./HealthDot";

function Item({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const here = inArea(item, useLocation().pathname);
  const link = (
    <NavLink to={item.path} className={`sh-nav-link${here ? " active" : ""}`} aria-current={here ? "page" : undefined}>
      <item.icon size={18} aria-hidden />
      <span className="sh-label">{item.label}</span>
    </NavLink>
  );
  return <li>{collapsed ? <Tooltip content={item.label} side="right">{link}</Tooltip> : link}</li>;
}

export function Sidebar() {
  const collapsed = useStore(sidebarCollapsed);
  const items = [...visibleCore(useStore(sidebarPrefs)), ...enabledApps(useStore(appsOn))];
  return (
    <aside className="sh-sidebar" data-collapsed={collapsed || undefined}>
      <div className="sh-brand">
        <span className="sh-mark" aria-hidden>
          g
        </span>
        <span className="sh-label sh-brand-name">go-high</span>
      </div>
      <nav aria-label="Primary" className="sh-nav">
        <ul>
          <Item item={MY_DAY_NAV} collapsed={collapsed} />
          {items.map((i) => (
            <Item key={i.id} item={i} collapsed={collapsed} />
          ))}
        </ul>
      </nav>
      <nav aria-label="Secondary" className="sh-nav sh-nav-bottom">
        <ul>
          <Item item={APPS_NAV} collapsed={collapsed} />
          <Item item={SETTINGS_NAV} collapsed={collapsed} />
        </ul>
      </nav>
      <div className="sh-sidebar-foot">
        <HealthDot showLabel />
        <Button
          variant="ghost"
          size="icon"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          onClick={() => sidebarCollapsed.set(!collapsed)}
        >
          {collapsed ? <PanelLeftOpen size={18} aria-hidden /> : <PanelLeftClose size={18} aria-hidden />}
        </Button>
      </div>
    </aside>
  );
}
