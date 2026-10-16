import { LinkIcon, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api, ApiError, errorText } from "../lib/api";
import { refreshMe, session } from "../lib/session";
import { Button } from "../ui";
import { AuthLayout } from "./AuthLayout";

type State = { kind: "working" } | { kind: "invalid" } | { kind: "error"; message: string };

/** /auth/magic?token=...: spends the one-time token with a POST (never a GET, so mail scanners cannot burn it). */
export function MagicLink() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [token] = useState(() => params.get("token"));
  const [state, setState] = useState<State>(token ? { kind: "working" } : { kind: "invalid" });
  const started = useRef(false);

  const consume = async () => {
    setState({ kind: "working" });
    try {
      await api.post("/api/auth/magic-link/consume", { token });
      await refreshMe();
      const s = session.get();
      if (s.status === "ready") return navigate("/", { replace: true });
      setState({ kind: "error", message: s.status === "error" ? s.message : "Signed in, but we could not load your account." });
    } catch (e) {
      navigate("/auth/magic", { replace: true }); // the token must not linger in the address bar or history
      setState(e instanceof ApiError && e.status === 401 ? { kind: "invalid" } : { kind: "error", message: errorText(e) });
    }
  };

  useEffect(() => {
    // StrictMode runs effects twice in development; a single-use token must be spent exactly once.
    if (!token || started.current) return;
    started.current = true;
    void consume();
  }, []);

  if (state.kind === "working")
    return (
      <AuthLayout title="Signing you in" icon={LinkIcon}>
        <p className="au-busy" role="status">
          <LoaderCircle className="ui-spin" size={16} aria-hidden />
          Checking your link
        </p>
      </AuthLayout>
    );

  if (state.kind === "error")
    return (
      <AuthLayout title="We could not sign you in" subtitle={state.message} icon={LinkIcon}>
        <div className="au-actions">
          <Button variant="primary" onClick={consume}>
            Try again
          </Button>
          <Button variant="ghost" onClick={() => navigate("/signin")}>
            Back to sign in
          </Button>
        </div>
      </AuthLayout>
    );

  return (
    <AuthLayout title="This link no longer works" subtitle="Sign-in links can be used once and expire after a short time. Request a new one and we will email it right away." icon={LinkIcon}>
      <div className="au-actions">
        <Button variant="primary" onClick={() => navigate("/signin?mode=link")}>
          Email me a new link
        </Button>
        <Button variant="ghost" onClick={() => navigate("/signin")}>
          Back to sign in
        </Button>
      </div>
    </AuthLayout>
  );
}
