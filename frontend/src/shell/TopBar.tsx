import { Bell, Keyboard, LogOut, Moon, Rows3, Search, SlidersHorizontal, Sun } from "lucide-react";
import { MOD } from "../lib/platform";
import { density, theme, toggleDensity, toggleTheme } from "../lib/prefs";
import { signOut, useMe } from "../lib/session";
import { useStore } from "../lib/store";
import { Avatar, Button, DropdownMenu, Kbd, MenuItem, MenuLabel, MenuSeparator, Tooltip } from "../ui";
import { HealthDot } from "./HealthDot";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

type Props = { onSearch: () => void; onCustomize: () => void; onShortcuts: () => void };

export function TopBar({ onSearch, onCustomize, onShortcuts }: Props) {
  const dark = useStore(theme) === "dark";
  const compact = useStore(density) === "compact";
  const user = useMe()?.user;
  return (
    <header className="sh-topbar">
      <WorkspaceSwitcher />

      <button type="button" className="sh-search" onClick={onSearch} aria-label="Search and run commands">
        <Search size={16} aria-hidden />
        <span className="sh-search-text">Search or run a command</span>
        <span className="sh-search-keys" aria-hidden>
          <Kbd>{MOD}</Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>

      <div className="sh-topbar-actions">
        <DropdownMenu
          label="Notifications"
          trigger={
            <Button variant="ghost" size="icon" aria-label="Notifications">
              <Bell size={18} aria-hidden />
            </Button>
          }
        >
          <MenuLabel>Notifications</MenuLabel>
          <div className="sh-notify-empty">You are all caught up.</div>
        </DropdownMenu>

        <Tooltip content={dark ? "Switch to light theme" : "Switch to dark theme"}>
          <Button className="sh-theme-btn" variant="ghost" size="icon" aria-label={dark ? "Switch to light theme" : "Switch to dark theme"} onClick={toggleTheme}>
            {dark ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
          </Button>
        </Tooltip>

        <DropdownMenu
          label="Profile"
          trigger={
            <Button variant="ghost" size="icon" aria-label="Profile menu">
              <Avatar name={user?.name ?? "Account"} size="sm" />
            </Button>
          }
        >
          {user && (
            <div className="sh-profile-id">
              <strong>{user.name}</strong>
              <span>{user.email}</span>
            </div>
          )}
          <MenuSeparator />
          <MenuItem icon={dark ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />} onSelect={toggleTheme}>
            {dark ? "Light theme" : "Dark theme"}
          </MenuItem>
          <MenuItem icon={<Rows3 size={16} aria-hidden />} onSelect={toggleDensity}>
            {compact ? "Comfortable density" : "Compact density"}
          </MenuItem>
          <MenuItem icon={<SlidersHorizontal size={16} aria-hidden />} onSelect={onCustomize}>
            Customize sidebar
          </MenuItem>
          <MenuItem icon={<Keyboard size={16} aria-hidden />} onSelect={onShortcuts}>
            Keyboard shortcuts
          </MenuItem>
          <MenuSeparator />
          <MenuItem icon={<LogOut size={16} aria-hidden />} onSelect={() => void signOut()}>
            Sign out
          </MenuItem>
          <MenuSeparator />
          <div className="sh-menu-status">
            <HealthDot showLabel />
          </div>
        </DropdownMenu>
      </div>
    </header>
  );
}
