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
