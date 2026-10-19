import { Ban, Clock, TriangleAlert, X } from "lucide-react";
import type { ReactNode } from "react";
import type { Refusal } from "./refusal.ts";

/** Why a message cannot go out, in the server's words, with what to do about it. Quiet hours say when sending resumes. */
export function RefusalBanner({ refusal, onDismiss, action }: { refusal: Refusal; onDismiss?: () => void; action?: ReactNode }) {
  const Icon = refusal.code === "quiet_hours" ? Clock : refusal.blocking ? Ban : TriangleAlert;
  return (
    <div className="ib-refusal" role="alert" data-code={refusal.code} data-tone={refusal.blocking ? "danger" : "warning"}>
      <Icon size={16} aria-hidden className="ib-refusal-icon" />
      <div className="ib-refusal-text">
        <strong>{refusal.title}</strong>
        <span className="ib-refusal-server">{refusal.text}</span>
        {refusal.until && (
          <span className="ib-refusal-until">
            You can send after <time>{refusal.until}</time>.
          </span>
        )}
        <span className="ib-refusal-hint">{refusal.hint}</span>
        {action}
      </div>
      {onDismiss && (
        <button type="button" className="ib-refusal-x" aria-label="Dismiss" onClick={onDismiss}>
          <X size={14} aria-hidden />
        </button>
      )}
    </div>
  );
}
