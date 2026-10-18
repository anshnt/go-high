import type { Definition } from "../forms-runtime/types";
import { summarize } from "./edit.ts";

const W = 240;
const H = 56;
const GAP = 44;
const X0 = 16;
const Y0 = 12;
const LANE = 22;
const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** The flow of the form: steps top to bottom, a jump as a curve to the right with the number of its rule, an end rule as a
 * green stop. The rules list under it is the same information as text. */
export function LogicMap({ def }: { def: Definition }) {
  const steps = def.steps;
  const index = new Map(steps.map((s, i) => [s.key, i]));
  const y = (i: number) => Y0 + i * (H + GAP);
  const rules = (def.logic ?? []).map((r, n) => ({ r, n }));
  const jumps = rules.filter(({ r }) => r.do === "jump" && index.has(r.from!) && index.has(r.target!));
  const ends = rules.filter(({ r }) => r.do === "end" && index.has(r.from!));
  // each jump gets the first lane to the right whose earlier jumps do not overlap it
  const lanes: { from: number; to: number }[][] = [];
  const laneOf = new Map<number, number>();
  for (const { r, n } of [...jumps].sort((a, b) => Math.abs(index.get(b.r.target!)! - index.get(b.r.from!)!) - Math.abs(index.get(a.r.target!)! - index.get(a.r.from!)!))) {
    const span = { from: index.get(r.from!)!, to: index.get(r.target!)! };
    let lane = lanes.findIndex((l) => l.every((o) => span.to <= o.from || span.from >= o.to));
    if (lane < 0) lane = lanes.push([]) - 1;
    lanes[lane]!.push(span);
    laneOf.set(n, lane);
  }
  const conditional = (key: string, fieldKeys: string[]) => (def.logic ?? []).filter((r) => (r.do === "show" || r.do === "hide") && (r.target === key || fieldKeys.includes(r.target ?? ""))).length;
  const width = X0 + W + 34 + 52 + Math.max(0, lanes.length - 1) * LANE + 16;
  const height = y(steps.length) + 40;

  return (
    <svg className="fm-map" viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="fm-map-title">
      <title id="fm-map-title">{`Flow of the form: ${steps.length} step${steps.length === 1 ? "" : "s"}, ${jumps.length} jump${jumps.length === 1 ? "" : "s"}, ${ends.length} early end${ends.length === 1 ? "" : "s"}`}</title>
      <defs>
        {["next", "jump", "end"].map((k) => (
          <marker key={k} id={`fm-arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className={`fm-arrow fm-arrow-${k}`} />
          </marker>
        ))}
      </defs>
      {steps.map((s, i) => (
        <line key={`n${s.key}`} className="fm-edge fm-edge-next" x1={X0 + W / 2} y1={y(i) + H} x2={X0 + W / 2} y2={y(i + 1) - 1} markerEnd="url(#fm-arrow-next)" />
      ))}
      {jumps.map(({ r, n }) => {
        const [a, b] = [y(index.get(r.from!)!) + H / 2, y(index.get(r.target!)!) + H / 2];
        const out = 26 + laneOf.get(n)! * LANE;
        const x = X0 + W;
        return (
          <g key={`j${n}`}>
            <title>{`Rule ${n + 1}: after step ${index.get(r.from!)! + 1}, go to step ${index.get(r.target!)! + 1} when ${summarize(r.when, def)}`}</title>
            <path className="fm-edge fm-edge-jump" d={`M${x},${a} C${x + out},${a} ${x + out},${b} ${x + 1},${b}`} markerEnd="url(#fm-arrow-jump)" />
            <circle className="fm-badge" cx={x + out * 0.75} cy={(a + b) / 2} r="9" />
            <text className="fm-badge-text" x={x + out * 0.75} y={(a + b) / 2} textAnchor="middle" dominantBaseline="central">
              {n + 1}
            </text>
          </g>
        );
      })}
      {ends.map(({ r, n }) => {
        const cy = y(index.get(r.from!)!) + H / 2 + 12;
        return (
          <g key={`e${n}`}>
            <title>{`Rule ${n + 1}: the form ends after step ${index.get(r.from!)! + 1} when ${summarize(r.when, def)}`}</title>
            <line className="fm-edge fm-edge-end" x1={X0 + W} y1={cy} x2={X0 + W + 32} y2={cy} markerEnd="url(#fm-arrow-end)" />
            <rect className="fm-stop" x={X0 + W + 34} y={cy - 11} width="52" height="22" rx="11" />
            <text className="fm-stop-text" x={X0 + W + 60} y={cy} textAnchor="middle" dominantBaseline="central">
              End {n + 1}
            </text>
          </g>
        );
      })}
      {steps.map((s, i) => {
        const c = conditional(s.key, s.fields.map((f) => f.key));
        return (
          <g key={s.key} className="fm-node">
            <rect x={X0} y={y(i)} width={W} height={H} rx="10" />
            <circle className="fm-node-num" cx={X0 + 22} cy={y(i) + H / 2} r="11" />
            <text className="fm-node-numtext" x={X0 + 22} y={y(i) + H / 2} textAnchor="middle" dominantBaseline="central">
              {i + 1}
            </text>
            <text className="fm-node-title" x={X0 + 44} y={y(i) + 23}>
              {clip(s.title || `Step ${i + 1}`, 26)}
            </text>
            <text className="fm-node-sub" x={X0 + 44} y={y(i) + 41}>
              {`${s.fields.length} item${s.fields.length === 1 ? "" : "s"}${c ? ` · ${c} conditional` : ""}`}
            </text>
          </g>
        );
      })}
      <g className="fm-node fm-node-send">
        <rect x={X0 + W / 2 - 50} y={y(steps.length)} width="100" height="28" rx="14" />
        <text className="fm-node-title" x={X0 + W / 2} y={y(steps.length) + 14} textAnchor="middle" dominantBaseline="central">
          Send
        </text>
      </g>
    </svg>
  );
}
