import { api } from "../lib/api";
import { recordsClient } from "../records/client.ts";
import { createPipelineApiClient } from "./apiClient.ts";
import type { PipelineClient } from "./types.ts";

// The demo build runs on the in-memory client over the demo's records; normal builds fold the condition to false, so the
// dynamic import goes with it and the in-memory client is not bundled.
const demo = import.meta.env.VITE_DEMO === "1" ? (await import("./memoryClient.ts")).createMemoryPipelineClient(recordsClient, { latency: 60 }) : undefined;

const live = createPipelineApiClient(api);

export const pipelineClient: PipelineClient = demo ?? live;
