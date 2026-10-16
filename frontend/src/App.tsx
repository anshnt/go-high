import { useEffect, useState } from "react";

type Health = { status: string; database: boolean; version: string };

// Placeholder until the app shell lands (#4): proves the web app talks to the API.
export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setError(true));
  }, []);

  return (
    <main>
      <h1>go-high</h1>
      <p>Growth platform for agencies and small businesses.</p>
      <p role="status">
        API: {error ? "unreachable" : health ? `${health.status}, v${health.version}` : "checking..."}
      </p>
    </main>
  );
}
