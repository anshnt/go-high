import { Bell, CheckCheck, Settings } from "lucide-react";
import { useNavigate } from "react-router";
import { timeAgo } from "../lib/device";
import { markRead, refreshNotifications, useNotifications, type Notification } from "../lib/notifications";
import { Button, DropdownMenu, MenuItem, MenuLabel, MenuSeparator } from "../ui";

/** The bell in the top bar: the unread count, and the latest notifications to read, open or mark read. */
export function NotificationBell() {
  const { unread, items, loaded } = useNotifications();
  const navigate = useNavigate();

  const open = (n: Notification) => {
    if (!n.read_at) void markRead([n.id]);
    if (n.link) navigate(n.link);
  };

  return (
    <DropdownMenu
      label="Notifications"
      className="sh-notify"
      onOpenChange={(isOpen) => isOpen && void refreshNotifications()}
      trigger={
        <Button variant="ghost" size="icon" className="sh-bell" aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}>
          <Bell size={18} aria-hidden />
          {unread > 0 && (
            <span className="sh-bell-badge" aria-hidden>
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Button>
      }
    >
      <div className="sh-notify-head">
        <MenuLabel>Notifications</MenuLabel>
        <MenuItem
          className="sh-notify-all"
          disabled={unread === 0}
          onSelect={(e) => {
            e.preventDefault(); // keep the list open so the dots clear in front of you
            void markRead("all");
          }}
        >
          <CheckCheck size={14} aria-hidden />
          Mark all read
        </MenuItem>
      </div>
      {!loaded ? (
        <div className="sh-notify-empty">Loading</div>
      ) : items.length === 0 ? (
        <div className="sh-notify-empty">You are all caught up.</div>
      ) : (
        <div className="sh-notify-list">
          {items.map((n) => (
            <MenuItem key={n.id} className="sh-notify-item" data-unread={!n.read_at || undefined} onSelect={() => open(n)}>
              <span className="sh-notify-dot" aria-hidden />
              <span className="sh-notify-text">
                <span className="sh-notify-title">
                  {!n.read_at && <span className="sr-only">Unread: </span>}
                  {n.title}
                </span>
                {n.body && <span className="sh-notify-body">{n.body}</span>}
                <time className="sh-notify-time" dateTime={n.created_at}>
                  {timeAgo(n.created_at)}
                </time>
              </span>
            </MenuItem>
          ))}
        </div>
      )}
      <MenuSeparator />
      <MenuItem icon={<Settings size={16} aria-hidden />} onSelect={() => navigate("/settings/notifications")}>
        Notification settings
      </MenuItem>
    </DropdownMenu>
  );
}
