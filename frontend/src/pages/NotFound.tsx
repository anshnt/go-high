import { Compass } from "lucide-react";
import { Link } from "react-router";
import { PageHeader } from "../shell/PageHeader";
import { EmptyState } from "../ui";

export function NotFound() {
  return (
    <div className="sh-page">
      <PageHeader title="Page not found" />
      <EmptyState
        icon={Compass}
        title="We could not find that page"
        text="It may have moved or never existed. Press Ctrl or Cmd plus K to search."
        action={
          <Link to="/inbox" className="ui-btn" data-variant="primary" data-size="md">
            Go to Inbox
          </Link>
        }
      />
    </div>
  );
}
