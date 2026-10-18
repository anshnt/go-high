import { Link } from "react-router";
import { APPS, appsOn } from "../lib/nav";
import { useStore } from "../lib/store";
import { PageHeader } from "../shell/PageHeader";
import { Badge, Switch } from "../ui";

export function AppsPage() {
  const on = useStore(appsOn);
  const toggle = (id: string, show: boolean) => appsOn.set(show ? [...on, id] : on.filter((x) => x !== id));
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
                {a.path ? <Switch aria-label={`Show ${a.label} in the sidebar`} checked={on.includes(a.id)} onCheckedChange={(show) => toggle(a.id, show)} /> : <Badge>Coming soon</Badge>}
              </div>
              <p>{a.blurb}</p>
              {a.path && on.includes(a.id) && (
                <Link to={a.path} className="sh-card-link">
                  Open {a.label}
                </Link>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
