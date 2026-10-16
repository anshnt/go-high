import { useEffect, type ReactNode } from "react";

/** Title row with an optional primary action, and an optional row for saved-view tabs. */
export function PageHeader({ title, description, views, actions }: { title: string; description?: string; views?: ReactNode; actions?: ReactNode }) {
  useEffect(() => {
    document.title = `${title} | go-high`;
  }, [title]);
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
