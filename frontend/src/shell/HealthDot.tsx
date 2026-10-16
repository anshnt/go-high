import { healthLabel, useHealth } from "../lib/health";

/** Small API status indicator; the text is always available to screen readers. */
export function HealthDot({ showLabel }: { showLabel?: boolean }) {
  const h = useHealth();
  return (
    <span className="sh-health" data-state={h.state} role="status">
      <span className="sh-dot" aria-hidden />
      <span className={showLabel ? "sh-label" : "sr-only"}>{healthLabel(h)}</span>
    </span>
  );
}
