import type { NavItem } from "../lib/nav";
import { PageHeader } from "../shell/PageHeader";
import { EmptyState } from "../ui";

/** Calm placeholder for a core module that has not been built yet. No fake data. */
export function ModulePage({ item }: { item: NavItem }) {
  return (
    <div className="sh-page">
      <PageHeader title={item.label} />
      <EmptyState icon={item.icon} title={`${item.label} is on the way`} text={item.blurb} />
    </div>
  );
}
