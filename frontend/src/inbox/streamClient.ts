// One EventSource for the tab while the inbox is open (GET /api/v1/stream, README "Realtime"). Subscribers get each
// event; when the connection is lost for good it reconnects with a growing pause and tells them to refetch
// everything (`stream.resync`), because a fresh EventSource cannot ask the server to resume from where it was.
// While the browser is retrying by itself it sends Last-Event-ID and the server fills the gap. The demo has no server:
// the same events come from lib/demoInbox, so the screen runs the same code.
import { workspaceId } from "../lib/api";
import { memory, useStore } from "../lib/store";
import { backoff, parseEvent, type StreamEvent } from "./stream";

export type StreamStatus = "off" | "connecting" | "open" | "retrying";
const status = memory<StreamStatus>("off");
export const useStreamStatus = () => useStore(status);

type Listener = (e: StreamEvent) => void;
const listeners = new Set<Listener>();
const emit = (e: StreamEvent) => listeners.forEach((fn) => fn(e));

let source: EventSource | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let attempt = 0;
let lost = false; // the last EventSource was dropped, so the next one must resync
let stopDemo: (() => void) | undefined;

function connect() {
  clearTimeout(timer);
  const ws = workspaceId.get();
  if (!ws || typeof EventSource === "undefined") return;
  status.set("connecting");
  const es = new EventSource(`/api/v1/stream?workspace_id=${encodeURIComponent(ws)}`);
  source = es;
  es.onopen = () => {
    attempt = 0;
    status.set("open");
    if (lost) {
      lost = false;
      emit({ type: "stream.resync" });
    }
  };
  es.onmessage = (m) => {
    const e = parseEvent(String(m.data));
    if (e) emit(e);
  };
  es.onerror = () => {
    if (es.readyState !== EventSource.CLOSED) return void status.set("connecting"); // the browser is retrying, with Last-Event-ID
    es.close();
    if (source === es) source = null;
    lost = true;
    status.set("retrying");
    timer = setTimeout(connect, backoff(attempt++));
  };
}

const wake = () => {
  if (source || !listeners.size || document.visibilityState === "hidden") return;
  attempt = 0;
  connect();
};

function start() {
  if (import.meta.env.VITE_DEMO === "1") {
    status.set("open");
    void import("../lib/demoInbox").then((m) => {
      if (listeners.size) stopDemo = m.demoEvents.listen(emit);
    });
    return;
  }
  connect();
  document.addEventListener("visibilitychange", wake);
  window.addEventListener("online", wake);
}

function stop() {
  clearTimeout(timer);
  source?.close();
  source = null;
  stopDemo?.();
  stopDemo = undefined;
  lost = false;
  attempt = 0;
  status.set("off");
  document.removeEventListener("visibilitychange", wake);
  window.removeEventListener("online", wake);
}

/** Listens to the stream; the connection opens with the first listener and closes with the last. */
export function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  if (listeners.size === 1) start();
  return () => {
    listeners.delete(fn);
    if (!listeners.size) stop();
  };
}
