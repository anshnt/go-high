import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { api, ApiError, errorText, workspaceId } from "../lib/api";
import { safeNext } from "../lib/safeNext";
import { ensureMe, refreshMe, session, useSession } from "../lib/session";
import { Button, Input } from "../ui";
import { AuthLayout, FormError } from "./AuthLayout";
import { emailError, FOCUS_FIRST, MIN_PASSWORD, passwordHint } from "./fields";

type Errors = { name?: string; email?: string; password?: string; form?: string };

export function SignUp() {
  const [params] = useSearchParams();
  const status = useSession().status;
  const next = safeNext(params.get("next"));
  const query = next === "/" ? "" : `?next=${encodeURIComponent(next)}`;

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [org, setOrg] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => ensureMe(), []);
  if (status === "ready") return <Navigate to={next} replace />;

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    const found: Errors = {
      name: name.trim() ? undefined : "Enter your name.",
      email: emailError(email),
      password: password.length >= MIN_PASSWORD ? undefined : `Use at least ${MIN_PASSWORD} characters.`,
    };
    if (found.name || found.email || found.password) return setErrors(found);
    setErrors({});
    setBusy(true);
    try {
      const body = { name: name.trim(), email: email.trim(), password, ...(org.trim() ? { org_name: org.trim() } : {}) };
      const res = await api.post<{ workspace_id: string }>("/api/auth/signup", body);
      workspaceId.set(res.workspace_id); // land in the workspace that was just made
      await refreshMe(); // the redirect above takes over once the session is ready
      const s = session.get();
      if (s.status !== "ready") setErrors({ form: s.status === "error" ? s.message : "Account created, but we could not load it. Try signing in." });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setErrors({ email: "An account with this email already exists." });
      else setErrors({ form: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Start with a workspace of your own."
      footer={
        <>
          Already have an account? <Link to={`/signin${query}`}>Sign in</Link>
        </>
      }
    >
      <form className="au-form" onSubmit={submit} noValidate>
        <Input label="Your name" name="name" autoComplete="name" autoFocus={FOCUS_FIRST} value={name} error={errors.name} onChange={(e) => setName(e.target.value)} />
        <Input
          label="Email"
          type="email"
          name="email"
          autoComplete="username"
          inputMode="email"
          value={email}
          error={errors.email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Input
          label="Password"
          type="password"
          name="password"
          autoComplete="new-password"
          value={password}
          error={password.length < MIN_PASSWORD ? errors.password : undefined}
          hint={passwordHint(password)}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Input
          label="Organization name (optional)"
          name="organization"
          autoComplete="organization"
          hint="We use your name if you leave this blank."
          value={org}
          onChange={(e) => setOrg(e.target.value)}
        />
        <FormError>{errors.form}</FormError>
        <Button type="submit" variant="primary" loading={busy}>
          Create account
        </Button>
      </form>
    </AuthLayout>
  );
}
