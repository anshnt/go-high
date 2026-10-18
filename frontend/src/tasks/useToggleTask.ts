import { useCallback } from "react";
import { errorText } from "../lib/api";
import { dueLabel } from "../lib/dates";
import { completeTask, deleteTask, reopenTask, touch, type Task } from "../lib/tasks";
import { useToast } from "../ui";

/**
 * Finishes an open task or reopens a finished one. Finishing offers an undo, which reopens it and removes the next
 * occurrence a repeating task created. Callers show the new state at once and reload (`touch`) when this settles.
 */
export function useToggleTask() {
  const toast = useToast();
  return useCallback(
    async (task: Task) => {
      try {
        if (task.status === "done") {
          await reopenTask(task.id);
          toast({ title: "Task reopened", description: task.title, tone: "success" });
          return;
        }
        const done = await completeTask(task.id);
        toast({
          title: "Task completed",
          description: done.next ? `${task.title}. Next: ${dueLabel(done.next, new Date())}` : task.title,
          tone: "success",
          action: {
            label: "Undo",
            onClick: () => {
              reopenTask(task.id)
                .then(() => (done.next ? deleteTask(done.next.id) : undefined))
                .catch((e) => toast({ title: "Could not undo", description: errorText(e), tone: "danger" }))
                .finally(touch);
            },
          },
        });
      } catch (e) {
        toast({ title: "Could not update the task", description: errorText(e), tone: "danger" });
      } finally {
        touch();
      }
    },
    [toast],
  );
}
