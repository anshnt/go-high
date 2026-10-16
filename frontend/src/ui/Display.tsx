import { useState, type ComponentType, type CSSProperties, type ReactNode } from "react";
import { cn } from "../lib/cn";

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

export const Badge = ({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) => (
  <span className="ui-badge" data-tone={tone}>
    {children}
  </span>
);

export const Kbd = ({ children }: { children: ReactNode }) => <kbd className="ui-kbd">{children}</kbd>;

export const Skeleton = ({ className, style }: { className?: string; style?: CSSProperties }) => (
  <span className={cn("ui-skeleton", className)} style={style} aria-hidden />
);

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");

export function Avatar({ name, src, size = "md" }: { name: string; src?: string; size?: "sm" | "md" }) {
  const [broken, setBroken] = useState(false);
  return (
    <span className="ui-avatar" data-size={size} role="img" aria-label={name}>
      {src && !broken ? <img src={src} alt="" onError={() => setBroken(true)} /> : initials(name)}
    </span>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  text,
  action,
}: {
  icon: ComponentType<{ size?: number; "aria-hidden"?: boolean }>;
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="ui-empty">
      <span className="ui-empty-icon">
        <Icon size={20} aria-hidden />
      </span>
      <h2>{title}</h2>
      <p>{text}</p>
      {action}
    </div>
  );
}
