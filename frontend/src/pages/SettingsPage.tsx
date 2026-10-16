import { ChevronRight, SearchX } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { SETTINGS, SETTINGS_NAV } from "../lib/nav";
import { fuzzy } from "../lib/fuzzy";
import { PageHeader } from "../shell/PageHeader";
import { Button, EmptyState, Input } from "../ui";

export function SettingsPage() {
  const [query, setQuery] = useState("");
  const shown = SETTINGS.filter((s) => fuzzy(query, `${s.label} ${s.keywords}`) !== null);
  return (
    <div className="sh-page">
      <PageHeader title="Settings" description="Every setting lives in exactly one place." />
      <div className="sh-settings-search">
        <Input type="search" aria-label="Search settings" placeholder="Search settings" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      {shown.length === 0 ? (
        <EmptyState icon={SearchX} title="No matching settings" text={`Nothing matches "${query}". Try a shorter word.`} action={<Button onClick={() => setQuery("")}>Clear search</Button>} />
      ) : (
        <ul className="sh-settings-list">
          {shown.map((s) => (
            <li key={s.id}>
              <Link to={`/settings/${s.id}`} className="sh-settings-row">
                <span>
                  <strong>{s.label}</strong>
                  <span className="sh-settings-blurb">{s.blurb}</span>
                </span>
                <ChevronRight size={16} aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Deep link target for one section: /settings/:sectionId */
export function SettingsSectionPage() {
  const { sectionId } = useParams();
  const s = SETTINGS.find((x) => x.id === sectionId);
  return (
    <div className="sh-page">
      <PageHeader title={s?.label ?? "Setting not found"} />
      <EmptyState
        icon={SETTINGS_NAV.icon}
        title={s ? `${s.label} settings are on the way` : "This setting does not exist"}
        text={s ? s.blurb : "Check the address or search for it from the settings list."}
        action={
          <Link to="/settings" className="ui-btn" data-variant="secondary" data-size="md">
            Back to settings
          </Link>
        }
      />
    </div>
  );
}
