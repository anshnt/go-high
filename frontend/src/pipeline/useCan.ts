import { workspaceId } from "../lib/api";
import { useMe } from "../lib/session";
import { useStore } from "../lib/store";
import { canOf, type Can } from "./can.ts";

/** What the signed-in user's role in the current workspace may do here. */
export function useCan(): Can {
  const me = useMe();
  const id = useStore(workspaceId);
  return canOf(me?.workspaces.find((w) => w.id === id)?.role);
}
