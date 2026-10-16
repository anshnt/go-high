import { MailCheck } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { waitText } from "../lib/device";
import { api, ApiError, errorText } from "../lib/api";
import { safeNext } from "../lib/safeNext";
import { ensureMe, refreshMe, session, useSession } from "../lib/session";
import { Button, Input } from "../ui";
import { AuthLayout, FormError } from "./AuthLayout";
import { emailError, FOCUS_FIRST } from "./fields";

type View = "password" | "link" | "sent";

/** Path and query of a dev-exposed sign-in link, so it opens on this origin (the API may name another host). */
const devPath = (link: string) => {
  try {
    const u = new URL(link, location.origin);
    return u.pathname === "/auth/magic" ? u.pathname + u.search : null;
  } catch {
    return null;
  }
};

function signInMessage(e: unknown) {
  if (e instanceof ApiError && e.status === 401) return "Wrong email or password.";
  if (e instanceof ApiError && e.status === 429) return e.retryAfter ? `Too many attempts. Try again in ${waitText(e.retryAfter)}.` : "Too many attempts. Try again later.";
  return errorText(e);
}

export function SignIn() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const status = useSession().status;
  const next = safeNext(params.get("next"));
  const query = next === "/" ? "" : `?next=${encodeURIComponent(next)}`;

  const [view, setView] = useState<View>(params.get("mode") === "link" ? "link" : "password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string; form?: string }>({});
  const [busy, setBusy] = useState(false);
  const [devLink, setDevLink] = useState<string | null>(null);

  useEffect(() => ensureMe(), []);
  if (status === "ready") return <Navigate to={next} replace />;

  const fail = (e: { email?: string; password?: string; form?: string }) => setErrors(e);

  async function signIn(ev: FormEvent) {
    ev.preventDefault();
    const bad = emailError(email);
    if (bad || !password) return fail({ email: bad, password: password ? undefined : "Enter your password." });
    setErrors({});
    setBusy(true);
    try {
      await api.post("/api/auth/signin", { email: email.trim(), password });
      await refreshMe(); // the redirect above takes over once the session is ready
      const s = session.get();
      if (s.status !== "ready") fail({ form: s.status === "error" ? s.message : "Signed in, but we could not load your account. Try again." });
    } catch (e) {
      fail({ form: signInMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  async function sendLink(ev: FormEvent) {
    ev.preventDefault();
    const bad = emailError(email);
    if (bad) return fail({ email: bad });
    setErrors({});
    setBusy(true);
    try {
      const res = await api.post<{ link?: string }>("/api/auth/magic-link", { email: email.trim() });
      setDevLink(res.link ? devPath(res.link) : null);
      setView("sent");
    } catch (e) {
      fail({ form: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  const emailField = (
    <Input
      label="Email"
      type="email"
      name="email"
      autoComplete="username"
      autoFocus={FOCUS_FIRST}
      inputMode="email"
      value={email}
      error={errors.email}
      onChange={(e) => setEmail(e.target.value)}
    />
  );
  const back = (to: View) => () => {
    setErrors({});
    setView(to);
  };

  if (view === "sent") {
    return (
      <AuthLayout title="Check your email" icon={MailCheck}>
        <p className="au-sub">
          If <strong>{email.trim()}</strong> has an account, a sign-in link is on its way. The link works once and expires soon.
        </p>
        {devLink && (
          <div className="au-dev">
            <p>Shown only because this server exposes sign-in links for local development.</p>
            <Button variant="secondary" onClick={() => navigate(devLink)}>
              Dev only: open sign-in link
            </Button>
          </div>
        )}
        <div className="au-actions">
          <Button onClick={back("link")}>Send another link</Button>
          <Button variant="ghost" onClick={back("password")}>
            Back to sign in
          </Button>
        </div>
      </AuthLayout>
    );
  }

  if (view === "link") {
    return (
      <AuthLayout
        title="Email me a sign-in link"
        subtitle="We will send a one-time link to your inbox. No password needed."
        footer={
          <>
            New here? <Link to={`/signup${query}`}>Create an account</Link>
          </>
        }
      >
        <form className="au-form" onSubmit={sendLink} noValidate>
          {emailField}
          <FormError>{errors.form}</FormError>
          <Button type="submit" variant="primary" loading={busy}>
            Send sign-in link
          </Button>
          <Button variant="ghost" onClick={back("password")}>
            Use a password instead
          </Button>
        </form>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Welcome back to go-high."
      footer={
        <>
          New here? <Link to={`/signup${query}`}>Create an account</Link>
        </>
      }
    >
      <form className="au-form" onSubmit={signIn} noValidate>
        {emailField}
        <Input
          label="Password"
          type="password"
          name="password"
          autoComplete="current-password"
          value={password}
          error={errors.password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <FormError>{errors.form}</FormError>
        <Button type="submit" variant="primary" loading={busy}>
          Sign in
        </Button>
        <div className="au-or" aria-hidden>
          or
        </div>
        <Button onClick={back("link")}>Email me a sign-in link</Button>
      </form>
    </AuthLayout>
  );
}
