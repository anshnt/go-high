import { textParts } from "./text.ts";

/** Message text: search hits marked, web addresses as links that open in a new tab. Whitespace kept. */
export function MessageText({ text, q = "", className }: { text: string; q?: string; className?: string }) {
  return (
    <p className={className}>
      {textParts(text, q).map((p, i) => {
        const inner = p.hit ? <mark key={i}>{p.text}</mark> : p.text;
        return p.href ? (
          <a key={i} href={p.href} target="_blank" rel="noopener noreferrer nofollow">
            {inner}
          </a>
        ) : (
          <span key={i}>{inner}</span>
        );
      })}
    </p>
  );
}
