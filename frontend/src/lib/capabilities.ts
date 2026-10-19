// What the signed-in user's role may do in the current workspace, from GET /api/v1/me/capabilities (one read per
// workspace). `can("channels.manage")` decides what to OFFER and the server decides what to ALLOW, so a screen never
// guesses from a role's name (see holds.ts for why an unknown answer is a yes). Screens that must not show anything
// before they know (Settings > Channels) read `ready`.
import { useEffect } from "react";
import { api, workspaceId } from "./api";
import { holds } from "./holds";
import { memory, useStore } from "./store";

export type ObjectAccess = { scope: "all" | "own" | "own_and_unassigned" | "team" | "none"; rule_scope?: string; hidden_fields: string[]; readonly_fields: string[]; can: Record<"read" | "write" | "delete" | "export", boolean> };
export type Capabilities = {
  role: { id: string; key: string; name: string; source: "organization" | "workspace" } | null;
  capabilities: string[];
  teams: { id: string; name: string; direct: boolean }[];
  objects: Record<string, ObjectAccess>;
};
type State = { workspace: string | null; ready: boolean; caps: ReadonlySet<string>; data: Capabilities | null };

export const capabilities = memory<State>({ workspace: null, ready: false, caps: new Set(), data: null });

/** Outside a component: `can("tasks.write")`. In one, use `useCan()` so it renders again when the answer arrives. */
export const can = (capability: string) => holds(capabilities.get(), capability);

export async function loadCapabilities(ws: string | null): Promise<void> {
  if (!ws) return;
  try {
    const data = await api.get<Capabilities>("/api/v1/me/capabilities");
    if (workspaceId.get() === ws) capabilities.set({ workspace: ws, ready: true, caps: new Set(data.capabilities), data });
  } catch {
    /* keep what we had: the API refuses anything the role may not do */
  }
}

/** Mounted once in the shell: reads the capabilities for the workspace in use, and again when it changes or the tab returns. */
export function useLoadCapabilities() {
  const ws = useStore(workspaceId);
  useEffect(() => {
    if (capabilities.get().workspace !== ws) capabilities.set({ workspace: ws, ready: false, caps: new Set(), data: null });
    void loadCapabilities(ws);
    const visible = () => document.visibilityState === "visible" && void loadCapabilities(ws);
    document.addEventListener("visibilitychange", visible);
    return () => document.removeEventListener("visibilitychange", visible);
  }, [ws]);
}

/** `{ can, ready }` that re-render the component when the capabilities arrive or change. */
export function useCan() {
  const s = useStore(capabilities);
  return { can: (capability: string) => holds(s, capability), ready: s.ready, data: s.data };
}
