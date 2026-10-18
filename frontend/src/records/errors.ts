// What a records client throws. The API client maps its HTTP errors to the same class, so screens
// only ever look at `status` (403 shows the permission-denied state) and `fields` (inline messages).
export class RecordsError extends Error {
  status: number;
  /** field key -> message, for 422 answers */
  fields?: Record<string, string>;
  constructor(status: number, message: string, fields?: Record<string, string>) {
    super(message);
    this.name = "RecordsError";
    this.status = status;
    this.fields = fields;
  }
}

const FALLBACK = "Something went wrong. Try again.";

/** Words for the user: our own errors and API errors (lib/api ApiError) carry a ready message, anything else does not. */
export function errorMessage(e: unknown): string {
  const named = e as { name?: unknown; message?: unknown } | null;
  return (e instanceof RecordsError || named?.name === "ApiError") && typeof named?.message === "string" ? named.message : FALLBACK;
}

/** HTTP status of one of those errors, 0 if unknown. */
export const errorStatus = (e: unknown): number => (typeof (e as { status?: unknown } | null)?.status === "number" ? (e as { status: number }).status : 0);
