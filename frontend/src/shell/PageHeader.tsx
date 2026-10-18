import { useEffect, type ReactNode } from "react";
import { inbox } from "../lib/notifications";
import { useStore } from "../lib/store";

/** Title row with an optional primary action, and an optional row for saved-view tabs. The tab title carries the unread count. */
export function PageHeader({ title, description, views, actions }: { title: string; description?: string; views?: ReactNode; actions?: ReactNode }) {
  const unread = useStore(inbox).unread;
  useEffect(() => {
    document.title = `${unread ? `(${unread}) ` : ""}${title} | go-high`;
  }, [title, unread]);
  return (
    <header className="sh-page-header">
      <div className="sh-page-title-row">
        <div className="sh-page-titles">
          <h1>{title}</h1>
          {description && <p>{description}</p>}
        </div>
        {actions && <div className="sh-page-actions">{actions}</div>}
      </div>
      {views}
    </header>
  );
}
