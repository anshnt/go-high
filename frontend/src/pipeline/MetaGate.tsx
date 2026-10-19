import { LockKeyhole, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { useRecordsClient } from "../records/client.ts";
import { errorMessage, errorStatus } from "../records/errors.ts";
import { MetaProvider, useLoadMeta } from "../records/meta.tsx";
import { Button, EmptyState } from "../ui";

/** Loads what the record editors need (objects, fields, people, tags) and provides it; shows the permission-denied, error and loading states of the page. */
export function MetaGate({ skeleton, children }: { skeleton: ReactNode; children: ReactNode }) {
  const client = useRecordsClient();
  const { meta, error, retry } = useLoadMeta(client);
  if (error) {
    const denied = errorStatus(error) === 403;
    return (
      <div className="rec-page">
        <EmptyState
          icon={denied ? LockKeyhole : TriangleAlert}
          title={denied ? "You do not have access to this" : "We could not load this page"}
          text={denied ? "Ask a workspace admin to give you access." : errorMessage(error)}
          action={denied ? undefined : <Button onClick={retry}>Try again</Button>}
        />
      </div>
    );
  }
  if (!meta) return <>{skeleton}</>;
  return <MetaProvider meta={meta}>{children}</MetaProvider>;
}
