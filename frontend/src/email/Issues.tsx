import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";
import type { Issue } from "./api";

const ICON = { error: CircleAlert, warning: TriangleAlert, info: Info };
const WORD = { error: "Must fix", warning: "Worth fixing", info: "Note" };

/** What a check found, errors first, each with its level in words (not only a color). */
export function IssueList({ issues, compact, empty = "Nothing to fix." }: { issues: Issue[]; compact?: boolean; empty?: string }) {
  if (!issues.length)
    return (
      <p className="em-issue" data-level="ok">
        <CircleCheck size={16} aria-hidden />
        <span>{empty}</span>
      </p>
    );
  return (
    <ul className="em-issues" data-compact={compact || undefined}>
      {issues.map((i, n) => {
        const Icon = ICON[i.level];
        return (
          <li key={`${i.code}-${n}`} className="em-issue" data-level={i.level}>
            <Icon size={16} aria-hidden />
            <span>
              <span className="sr-only">{WORD[i.level]}: </span>
              {i.message}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
