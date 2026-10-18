import { useEffect, useRef } from "react";
import { mountInto } from "../forms-runtime/host";
import type { Handle } from "../forms-runtime/runtime";
import type { Definition } from "../forms-runtime/types";
import { theme } from "../lib/prefs";
import { useStore } from "../lib/store";
import type { Kind, Settings } from "./api";

/** The real form runtime (the one that ships to visitors) running on the definition being edited. It saves nothing. */
export function Preview({ def, name, kind, settings }: { def: Definition; name: string; kind: Kind; settings: Settings }) {
  const host = useRef<HTMLDivElement>(null);
  const handle = useRef<Handle | null>(null);
  const dark = useStore(theme);
  const preview = { definition: def, name, kind, settings: { success_message: settings.success_message } };
  const latest = useRef(preview);
  latest.current = preview;
  useEffect(() => {
    handle.current = mountInto(host.current!, { theme: dark, preview: latest.current });
    return () => handle.current?.destroy();
  }, [dark, kind]);
  useEffect(() => handle.current?.update(def), [def]);
  return <div ref={host} className="fm-preview" />;
}
