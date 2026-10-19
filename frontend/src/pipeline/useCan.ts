import { useCan as useCapabilities } from "../lib/capabilities";

export type Can = { writeDeals: boolean; managePipelines: boolean };

/** What the board offers the signed-in user, from their role's capabilities in this workspace (the server decides). */
export function useCan(): Can {
  const { can } = useCapabilities();
  return { writeDeals: can("deals.write"), managePipelines: can("pipelines.manage") };
}
