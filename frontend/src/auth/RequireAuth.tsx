import { useEffect } from "react";
import { Navigate, useLocation } from "react-router";
import { ensureMe, retryMe, useSession } from "../lib/session";
import { Button } from "../ui";
import { Shell } from "../shell/Shell";
import { ShellSkeleton } from "../shell/ShellSkeleton";
import { AuthLayout } from "./AuthLayout";

/** Everything inside the app needs a signed-in user. While we find out, the shell's outline shows instead of a spinner. */
export function RequireAuth() {
  const s = useSession();
  const { pathname, search } = useLocation();
  useEffect(() => ensureMe(), []);

  if (s.status === "loading") return <ShellSkeleton />;
  if (s.status === "error")
    return (
      <AuthLayout title="We could not load your account" subtitle={s.message}>
        <div className="au-actions">
          <Button variant="primary" onClick={retryMe}>
            Try again
          </Button>
        </div>
      </AuthLayout>
    );
  if (s.status === "anon") {
    // After choosing to sign out there is nothing to come back to; after an expired session there is.
    const here = pathname + search;
    const to = s.left || here === "/" ? "/signin" : `/signin?next=${encodeURIComponent(here)}`;
    return <Navigate to={to} replace />;
  }
  return <Shell />;
}
