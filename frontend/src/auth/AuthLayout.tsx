import { CircleAlert, Moon, Sun, type LucideIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { theme, toggleTheme } from "../lib/prefs";
import { useStore } from "../lib/store";
import { Button, Tooltip } from "../ui";
import "./auth.css";

/** Calm centered card for the screens outside the app shell (sign in, sign up, magic link). */
export function AuthLayout({ title, subtitle, icon: Icon, children, footer }: { title: string; subtitle?: ReactNode; icon?: LucideIcon; children?: ReactNode; footer?: ReactNode }) {
  const dark = useStore(theme) === "dark";
  const label = dark ? "Switch to light theme" : "Switch to dark theme";
  useEffect(() => {
    document.title = `${title} | go-high`;
  }, [title]);
  return (
    <div className="au-page">
      <header className="au-top">
        <span className="au-brand">
          <span className="sh-mark" aria-hidden>
            g
          </span>
          go-high
        </span>
        <Tooltip content={label}>
          <Button variant="ghost" size="icon" aria-label={label} onClick={toggleTheme}>
            {dark ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
          </Button>
        </Tooltip>
      </header>
      <main className="au-main">
        <div className="au-card">
          {Icon && (
            <span className="au-icon">
              <Icon size={20} aria-hidden />
            </span>
          )}
          <h1>{title}</h1>
          {subtitle && <p className="au-sub">{subtitle}</p>}
          {children}
          {footer && <p className="au-foot">{footer}</p>}
        </div>
      </main>
    </div>
  );
}

export const FormError = ({ children }: { children?: string }) =>
  children ? (
    <p className="au-error" role="alert">
      <CircleAlert size={16} aria-hidden />
      <span>{children}</span>
    </p>
  ) : null;
