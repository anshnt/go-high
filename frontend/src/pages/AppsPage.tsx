import { APPS } from "../lib/nav";
import { PageHeader } from "../shell/PageHeader";
import { Badge } from "../ui";

export function AppsPage() {
  return (
    <div className="sh-page">
      <PageHeader title="Apps" description="Switch on only what you need. Each app appears in the sidebar once it is on." />
      <ul className="sh-cards">
        {APPS.map((a) => (
          <li key={a.id} className="sh-card">
            <span className="sh-card-icon">
              <a.icon size={18} aria-hidden />
            </span>
            <div className="sh-card-body">
              <div className="sh-card-top">
                <h2>{a.label}</h2>
                <Badge>Coming soon</Badge>
              </div>
              <p>{a.blurb}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
