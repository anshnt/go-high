// SMS segments and cost while typing. `smsSegments` counts the way the server does (backend/app/compliance.py
// `sms_segments`: GSM-7 with its extension table, else UCS-2), so the number shown at once is the number the estimate
// call then confirms; `segmentLabel` is the words under the box. Pure: no DOM, no Vite.
import type { Estimate } from "./types.ts";

// GSM 03.38: the basic table, and the extension table whose characters take an escape plus the character.
const GSM_BASIC = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà";
const GSM_EXTENSION = "\f^{}\\[~]|€";
const LIMITS = { gsm7: [160, 153], ucs2: [70, 67] } as const;

export function smsSegments(body: string): Pick<Estimate, "encoding" | "segments" | "chars"> {
  const chars = [...body];
  const gsm = chars.every((c) => GSM_BASIC.includes(c) || GSM_EXTENSION.includes(c));
  const encoding = gsm ? "gsm7" : "ucs2";
  // a character outside the basic plane (an emoji) is two UCS-2 units
  const widths = chars.map((c) => (gsm ? (GSM_EXTENSION.includes(c) ? 2 : 1) : c.length));
  const total = widths.reduce((n, w) => n + w, 0);
  const [single, part] = LIMITS[encoding];
  if (total <= single) return { encoding, segments: total > 0 ? 1 : 0, chars: total };
  let segments = 1;
  let room = part;
  for (const w of widths) {
    if (w > room) {
      segments += 1;
      room = part;
    }
    room -= w;
  }
  return { encoding, segments, chars: total };
}

/** "$0.0158" for a price per message, "" when there is none (a channel with no segment cost set). */
export function costLabel(cost: string | null | undefined): string {
  const n = Number(cost);
  if (!cost || !Number.isFinite(n) || n <= 0) return "";
  const digits = n >= 1 ? 2 : 4; // a segment costs fractions of a cent
  return `$${n.toFixed(digits).replace(/(\.\d*?[1-9])0+$|\.0+$/, "$1")}`;
}

/** "2 segments, 134 characters, about $0.016", or "Unicode: 3 segments" ... plain words under the composer. */
export function segmentLabel(e: Pick<Estimate, "encoding" | "segments" | "chars"> & { estimated_cost?: string | null }): string {
  if (e.segments === 0) return "";
  const parts = [`${e.segments} segment${e.segments === 1 ? "" : "s"}`, `${e.chars} character${e.chars === 1 ? "" : "s"}`];
  if (e.encoding === "ucs2") parts.push("Unicode, shorter segments");
  const cost = costLabel(e.estimated_cost);
  if (cost) parts.push(`about ${cost}`);
  return parts.join(" · ");
}

/** Characters left in the current segment, for a quiet counter ("27 left"). */
export function charsLeft(e: Pick<Estimate, "encoding" | "segments" | "chars">): number {
  if (e.segments === 0) return LIMITS[e.encoding][0];
  const [single, part] = LIMITS[e.encoding];
  return e.segments === 1 ? single - e.chars : part * e.segments - e.chars;
}
