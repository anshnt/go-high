import { useCallback, useEffect, useState } from "react";
import type { Pipeline, PipelineClient } from "./types.ts";

type State = { status: "loading" | "ready" | "error"; pipelines: Pipeline[]; error: unknown };

/** The workspace's live pipelines with their stages, in order. `reload` asks again (after settings changed them). */
export function usePipelines(client: PipelineClient) {
  const [state, setState] = useState<State>({ status: "loading", pipelines: [], error: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    client.list().then(
      (pipelines) => live && setState({ status: "ready", pipelines, error: null }),
      (error) => live && setState({ status: "error", pipelines: [], error }),
    );
    return () => {
      live = false;
    };
  }, [client, attempt]);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, reload };
}
