import { useEffect, useState } from "react";

export type Health = { state: "checking" | "ok" | "degraded" | "down"; version?: string };

// Subtle API status for the sidebar footer and profile menu, refreshed once a minute.
export function useHealth(): Health {
  const [health, setHealth] = useState<Health>({ state: "checking" });
  useEffect(() => {
    let alive = true;
    const check = () =>
      fetch("/api/health")
        .then((r) => r.json())
        .then((h: { status: string; database: boolean; version: string }) => {
          if (alive) setHealth({ state: h.status === "ok" && h.database ? "ok" : "degraded", version: h.version });
        })
        .catch(() => alive && setHealth({ state: "down" }));
    check();
    const id = setInterval(check, 60_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  return health;
}

export const healthLabel = (h: Health) =>
  h.state === "checking" ? "Checking API" : h.state === "ok" ? `API healthy${h.version ? `, v${h.version}` : ""}` : h.state === "degraded" ? "API degraded" : "API unreachable";
