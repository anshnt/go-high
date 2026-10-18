import { ChevronLeft, ListChecks } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError, api, errorText } from "../lib/api";
import { useMe } from "../lib/session";
import { useStore } from "../lib/store";
import { listTasks, tasksVersion, useMembers, type Task } from "../lib/tasks";
import { PageHeader } from "../shell/PageHeader";
import { Badge, EmptyState, Skeleton } from "../ui";
import { QuickAdd } from "./QuickAdd";
import { groupTasks, TaskList } from "./TaskList";
import { TaskRow } from "./TaskRow";
import { TaskSheet, type Target } from "./TaskSheet";
import { useToggleTask } from "./useToggleTask";
import "./tasks.css";

type Found = { id: string; object: string; display_name: string };

/**
 * Where a task's linked record opens, until the record page of module 07 exists: the record's name and the tasks on it.
 * ponytail: properties, timeline and associations come with that page; this one shows only what tasks need.
 */
export function RecordPage() {
  const { object, id } = useParams();
  const version = useStore(tasksVersion);
  const members = useMembers();
  const me = useMe()?.user.id ?? null;
  const toggle = useToggleTask();
  const [record, setRecord] = useState<Found | null | "missing">(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string>();
  const [sheet, setSheet] = useState<Target | null>(null);
  const now = new Date();

  useEffect(() => {
    let alive = true;
    api
      .get<Found>(`/api/v1/objects/${object}/records/${id}`)
      .then((r) => alive && setRecord(r))
      .catch((e) => alive && (e instanceof ApiError && e.status === 404 ? setRecord("missing") : setError(errorText(e))));
    return () => {
      alive = false;
    };
  }, [object, id]);

  useEffect(() => {
    let alive = true;
    listTasks({ record_id: id })
      .then((list) => alive && setTasks(list))
      .catch((e) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [id, version]);

  const open = useMemo(() => (tasks ?? []).filter((t) => t.status === "open"), [tasks]);
  const done = (tasks ?? []).filter((t) => t.status === "done");
  const name = record && record !== "missing" ? record.display_name : "Record";

  return (
    <div className="sh-page tk-page">
      <Link to="/tasks" className="sh-back">
        <ChevronLeft size={16} aria-hidden />
        Tasks
      </Link>
      <PageHeader title={record === "missing" ? "Record not found" : name} actions={record && record !== "missing" ? <Badge>{record.object}</Badge> : undefined} />
      {record === "missing" ? (
        <EmptyState icon={ListChecks} title="This record is not here" text="It may have been deleted, or it belongs to another workspace." />
      ) : error && !tasks ? (
        <EmptyState icon={ListChecks} title="Could not load this record" text={error} />
      ) : (
        <section aria-labelledby="record-tasks">
          <h2 id="record-tasks" className="tk-section-title">
            Tasks
          </h2>
          <QuickAdd assigneeId={me} recordId={id} placeholder={`Add a task for ${name}`} />
          {!tasks ? (
            <div className="tk-skeleton" aria-busy>
              <Skeleton style={{ height: 52 }} />
              <Skeleton style={{ height: 52 }} />
            </div>
          ) : open.length + done.length === 0 ? (
            <p className="tk-muted">No tasks on this record yet.</p>
          ) : (
            <>
              <TaskList groups={groupTasks(open, now)} members={members} now={now} onOpen={(t) => setSheet({ kind: "edit", id: t.id })} onToggle={(t) => void toggle(t)} />
              {done.length > 0 && (
                <section className="tk-group" aria-labelledby="record-done">
                  <h2 id="record-done" className="tk-group-title">
                    Completed<span className="tk-count">{done.length}</span>
                  </h2>
                  <ul className="tk-list">
                    {done.map((t) => (
                      <TaskRow key={t.id} task={t} members={members} now={now} onOpen={(x) => setSheet({ kind: "edit", id: x.id })} onToggle={(x) => void toggle(x)} />
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </section>
      )}
      {sheet && <TaskSheet key={sheet.kind === "edit" ? sheet.id : "new"} target={sheet} onClose={() => setSheet(null)} />}
    </div>
  );
}
