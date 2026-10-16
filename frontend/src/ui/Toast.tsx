import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { CircleAlert, CircleCheck, Info, X } from "lucide-react";

type Tone = "info" | "success" | "danger";
type ToastItem = {
  id: number;
  title: string;
  description?: string;
  tone: Tone;
  /** One button, for undo. Clicking it dismisses the toast. */
  action?: { label: string; onClick: () => void };
  /** Milliseconds on screen, default 5000. */
  duration?: number;
};

const Ctx = createContext<(t: Omit<ToastItem, "id" | "tone"> & { tone?: Tone }) => void>(() => {});
export const useToast = () => useContext(Ctx);

const icons = { info: Info, success: CircleCheck, danger: CircleAlert };

// Simple queue: newest last, at most 3 on screen, each leaves after 5s (or its own duration).
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(0);
  const dismiss = useCallback((id: number) => setItems((l) => l.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (t: Omit<ToastItem, "id" | "tone"> & { tone?: Tone }) => {
      const id = ++next.current;
      setItems((l) => [...l, { ...t, tone: t.tone ?? "info", id }].slice(-3));
      setTimeout(() => dismiss(id), t.duration ?? 5000);
    },
    [dismiss],
  );
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="ui-toasts" role="region" aria-label="Notifications" aria-live="polite">
        {items.map((t) => {
          const Icon = icons[t.tone];
          return (
            <div key={t.id} className="ui-toast" data-tone={t.tone} role="status">
              <Icon size={16} aria-hidden className="ui-toast-icon" />
              <div className="ui-toast-text">
                <strong>{t.title}</strong>
                {t.description && <p>{t.description}</p>}
              </div>
              {t.action && (
                <button
                  type="button"
                  className="ui-toast-action"
                  onClick={() => {
                    t.action!.onClick();
                    dismiss(t.id);
                  }}
                >
                  {t.action.label}
                </button>
              )}
              <button type="button" className="ui-toast-close" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
                <X size={14} aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
    </Ctx.Provider>
  );
}
