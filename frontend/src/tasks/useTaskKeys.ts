import { useEffect, useRef } from "react";
import type { Task } from "../lib/tasks";
import { TYPING } from "../shell/useShortcuts";

type Options = {
  /** The tasks in the order they are listed. */
  tasks: Task[];
  active: number;
  setActive: (index: number) => void;
  onToggle: (task: Task) => void;
  onEdit: (task: Task) => void;
  onNew: () => void;
};

/**
 * j and k move through a list of tasks, x completes (or reopens) the current one, e opens it and n adds a new one. Like
 * the other single-key shortcuts these pause while typing and while a dialog or sheet is open.
 */
export function useTaskKeys(options: Options) {
  const latest = useRef(options);
  latest.current = options;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.repeat && e.key !== "j" && e.key !== "k") return;
      const target = e.target as HTMLElement;
      if (target.closest(TYPING) || document.querySelector('[role="dialog"]')) return;
      const { tasks, active, setActive, onToggle, onEdit, onNew } = latest.current;
      const current = tasks[Math.min(active, tasks.length - 1)];
      if (e.key === "j" || e.key === "k") {
        if (!tasks.length) return;
        e.preventDefault();
        const next = Math.max(0, Math.min(tasks.length - 1, active + (e.key === "j" ? 1 : -1)));
        setActive(next);
        requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-task-id="${tasks[next]!.id}"] .tk-title`)?.focus());
      } else if (e.key === "x" && current) {
        e.preventDefault();
        onToggle(current);
      } else if (e.key === "e" && current) {
        e.preventDefault();
        onEdit(current);
      } else if (e.key === "n") {
        e.preventDefault();
        onNew();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
