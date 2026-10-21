// The block email builder: an outline of blocks (add, select, reorder, duplicate, delete, all from the keyboard), the
// selected block's settings or the design's colors, and a live preview rendered by the server's own renderer at phone
// and desktop width, light and dark, with the plain text part and the content lint beside it.
import { ArrowDown, ArrowUp, Copy, Monitor, Moon, Palette, Plus, Smartphone, Sun, Trash2, Type } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { errorText } from "../lib/api";
import { Badge, Button, DropdownMenu, Input, MenuItem, Select, Skeleton, Textarea, useToast } from "../ui";
import { Segmented } from "../ui/Segmented";
import { email, type Block, type BlockType, type Doc, type Issue, type MergeField, type Rendered, type Style } from "./api";
import { BLOCK_LABEL, byLevel, duplicateBlock, insertAt, moveBlock, newBlock, removeBlock, summary, updateBlock } from "./blocks";
import { IssueList } from "./Issues";

const TYPES: BlockType[] = ["heading", "text", "button", "image", "divider", "spacer", "columns"];
const ALIGN = [
  { value: "left", label: "Left" },
  { value: "center", label: "Center" },
  { value: "right", label: "Right" },
] as const;

type Props = {
  doc: Doc;
  onChange: (doc: Doc) => void;
  subject: string;
  preheader: string;
  /** server messages by block id */
  issues?: Record<string, string>;
  readOnly?: boolean;
};

export function Builder({ doc, onChange, subject, preheader, issues = {}, readOnly }: Props) {
  const toast = useToast();
  const [selected, setSelected] = useState<string | null>(doc.blocks[0]?.id ?? null);
  const [panel, setPanel] = useState<"block" | "style">("block");
  const [fields, setFields] = useState<MergeField[]>([]);
  const outline = useRef<HTMLOListElement>(null);
  useEffect(() => {
    email.mergeFields().then(setFields).catch(() => setFields([]));
  }, []);
  const block = doc.blocks.find((b) => b.id === selected) ?? null;

  const add = (type: BlockType) => {
    const b = newBlock(type);
    const at = selected ? doc.blocks.findIndex((x) => x.id === selected) + 1 : doc.blocks.length;
    onChange(insertAt(doc, at, b));
    setSelected(b.id!);
    setPanel("block");
  };
  const remove = (id: string) => {
    const before = doc;
    const i = doc.blocks.findIndex((b) => b.id === id);
    onChange(removeBlock(doc, id));
    setSelected(doc.blocks[i + 1]?.id ?? doc.blocks[i - 1]?.id ?? null);
    toast({ title: "Block deleted", tone: "info", action: { label: "Undo", onClick: () => onChange(before) } });
  };
  const focusItem = (id: string) => requestAnimationFrame(() => outline.current?.querySelector<HTMLButtonElement>(`[data-block="${id}"]`)?.focus());

  const onKey = (e: KeyboardEvent, id: string) => {
    if (readOnly) return;
    const i = doc.blocks.findIndex((b) => b.id === id);
    if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      e.preventDefault();
      onChange(moveBlock(doc, id, e.key === "ArrowUp" ? -1 : 1));
      focusItem(id);
    } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      const next = doc.blocks[i + (e.key === "ArrowUp" ? -1 : 1)];
      if (next?.id) {
        setSelected(next.id);
        focusItem(next.id);
      }
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      remove(id);
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "d") {
      e.preventDefault();
      onChange(duplicateBlock(doc, id));
    }
  };

  return (
    <div className="em-builder">
      <section className="em-edit" aria-label="Content">
        <div className="em-edit-head">
          <h2 className="em-h2">Blocks</h2>
          {!readOnly && (
            <DropdownMenu
              label="Add a block"
              align="start"
              trigger={
                <Button size="sm" aria-label="Add a block">
                  <Plus size={16} aria-hidden />
                  Add block
                </Button>
              }
            >
              {TYPES.map((t) => (
                <MenuItem key={t} onSelect={() => add(t)}>
                  {BLOCK_LABEL[t]}
                </MenuItem>
              ))}
            </DropdownMenu>
          )}
        </div>
        {doc.blocks.length === 0 ? (
          <p className="em-muted em-empty-blocks">No blocks yet. Add a heading, some text and a button to start.</p>
        ) : (
          <ol className="em-outline" ref={outline} aria-label="Blocks, in order. Alt and the arrow keys move the selected block.">
            {doc.blocks.map((b, i) => (
              <li key={b.id} className="em-outline-row" data-on={b.id === selected || undefined} data-invalid={issues[b.id!] ? true : undefined}>
                <button
                  type="button"
                  className="em-outline-item"
                  data-block={b.id}
                  aria-current={b.id === selected || undefined}
                  onClick={() => {
                    setSelected(b.id!);
                    setPanel("block");
                  }}
                  onKeyDown={(e) => onKey(e, b.id!)}
                >
                  <span className="em-outline-kind">{BLOCK_LABEL[b.type]}</span>
                  <span className="em-outline-sum">{summary(b)}</span>
                  {issues[b.id!] && <Badge tone="danger">Fix</Badge>}
                </button>
                {!readOnly && b.id === selected && (
                  <span className="em-outline-tools">
                    <Button variant="ghost" size="icon" aria-label="Move up" disabled={i === 0} onClick={() => onChange(moveBlock(doc, b.id!, -1))}>
                      <ArrowUp size={16} aria-hidden />
                    </Button>
                    <Button variant="ghost" size="icon" aria-label="Move down" disabled={i === doc.blocks.length - 1} onClick={() => onChange(moveBlock(doc, b.id!, 1))}>
                      <ArrowDown size={16} aria-hidden />
                    </Button>
                    <Button variant="ghost" size="icon" aria-label="Duplicate" onClick={() => onChange(duplicateBlock(doc, b.id!))}>
                      <Copy size={16} aria-hidden />
                    </Button>
                    <Button variant="ghost" size="icon" aria-label="Delete" onClick={() => remove(b.id!)}>
                      <Trash2 size={16} aria-hidden />
                    </Button>
                  </span>
                )}
              </li>
            ))}
          </ol>
        )}
        <div className="em-panel-switch">
          <Segmented
            label="Settings for"
            value={panel}
            onChange={setPanel}
            options={[
              { value: "block", label: "Block" },
              { value: "style", label: "Design" },
            ]}
          />
        </div>
        {panel === "style" ? (
          <StyleFields style={doc.style ?? {}} readOnly={readOnly} onChange={(style) => onChange({ ...doc, style })} />
        ) : block ? (
          <BlockFields block={block} fields={fields} error={issues[block.id!]} readOnly={readOnly} onChange={(patch) => onChange(updateBlock(doc, block.id!, patch))} />
        ) : (
          <p className="em-muted">Select a block to change it.</p>
        )}
      </section>
      <PreviewPane doc={doc} subject={subject} preheader={preheader} />
    </div>
  );
}

function MergeHint({ fields }: { fields: MergeField[] }) {
  if (!fields.length) return null;
  const shown = fields.filter((f) => !f.key.endsWith("_url")).slice(0, 6);
  return (
    <p className="ui-hint">
      Personalize with {shown.map((f, i) => (
        <span key={f.key}>
          {i ? ", " : ""}
          <code>{`{{${f.key}}}`}</code>
        </span>
      ))}
      ; add a fallback after a bar: <code>{"{{first_name|there}}"}</code>.
    </p>
  );
}

function BlockFields({ block, fields, error, readOnly, onChange }: { block: Block; fields: MergeField[]; error?: string; readOnly?: boolean; onChange: (patch: Partial<Block>) => void }) {
  const align = "align" in block && (
    <Select label="Alignment" value={block.align ?? "left"} options={[...ALIGN]} disabled={readOnly} onValueChange={(v) => onChange({ align: v as "left" })} />
  );
  return (
    <div className="em-fields" aria-label={`${BLOCK_LABEL[block.type]} settings`} role="group">
      {error && (
        <p className="em-field-error" role="alert">
          {error}
        </p>
      )}
      {block.type === "heading" && (
        <>
          <Input label="Heading" value={block.text} maxLength={300} disabled={readOnly} onChange={(e) => onChange({ text: e.target.value })} />
          <Select
            label="Size"
            value={String(block.level ?? 1)}
            disabled={readOnly}
            options={[
              { value: "1", label: "Large" },
              { value: "2", label: "Medium" },
              { value: "3", label: "Small" },
            ]}
            onValueChange={(v) => onChange({ level: Number(v) as 1 })}
          />
          {align}
          <MergeHint fields={fields} />
        </>
      )}
      {block.type === "text" && (
        <>
          <Textarea label="Text" rows={7} value={block.text} maxLength={5000} disabled={readOnly} onChange={(e) => onChange({ text: e.target.value })} hint="**bold**, _italic_, [link text](https://...). A blank line starts a new paragraph." />
          {align}
          <MergeHint fields={fields} />
        </>
      )}
      {block.type === "button" && (
        <>
          <Input label="Label" value={block.label} maxLength={80} disabled={readOnly} onChange={(e) => onChange({ label: e.target.value })} />
          <Input label="Link" type="url" value={block.url} disabled={readOnly} onChange={(e) => onChange({ url: e.target.value })} hint="https://... Links are tracked unless tracking is off in Email settings." />
          {align}
        </>
      )}
      {block.type === "image" && (
        <>
          <Input label="Image address" type="url" value={block.src} disabled={readOnly} onChange={(e) => onChange({ src: e.target.value })} hint="An https address. Images over 1 MB load slowly on phones." />
          <Input label="Alt text" value={block.alt ?? ""} maxLength={300} disabled={readOnly} onChange={(e) => onChange({ alt: e.target.value })} hint="What the image shows. People with images off, and screen readers, get this." />
          <Input label="Link (optional)" type="url" value={block.href ?? ""} disabled={readOnly} onChange={(e) => onChange({ href: e.target.value || null })} />
          <Input label="Width in pixels" type="number" min={16} max={600} value={block.width ?? 600} disabled={readOnly} onChange={(e) => onChange({ width: Number(e.target.value) || 600 })} />
          {align}
        </>
      )}
      {block.type === "spacer" && (
        <Input label="Height in pixels" type="number" min={4} max={96} value={block.height ?? 24} disabled={readOnly} onChange={(e) => onChange({ height: Number(e.target.value) || 24 })} />
      )}
      {block.type === "divider" && <p className="em-muted">A thin line between sections. It has no settings.</p>}
      {block.type === "columns" && <ColumnsFields block={block} fields={fields} readOnly={readOnly} onChange={onChange} />}
    </div>
  );
}

const INNER: BlockType[] = ["heading", "text", "button", "image", "spacer", "divider"];

function ColumnsFields({ block, fields, readOnly, onChange }: { block: Extract<Block, { type: "columns" }>; fields: MergeField[]; readOnly?: boolean; onChange: (patch: Partial<Block>) => void }) {
  const set = (c: number, blocks: Block[]) => onChange({ columns: block.columns.map((col, i) => (i === c ? { blocks } : col)) } as Partial<Block>);
  return (
    <>
      <Select
        label="Columns"
        value={String(block.columns.length)}
        disabled={readOnly}
        options={[
          { value: "2", label: "Two" },
          { value: "3", label: "Three" },
        ]}
        onValueChange={(v) =>
          onChange({ columns: Number(v) === 3 ? [...block.columns.slice(0, 3), ...(block.columns.length < 3 ? [{ blocks: [newBlock("text")] }] : [])] : block.columns.slice(0, 2) } as Partial<Block>)
        }
      />
      <p className="ui-hint">Columns sit side by side on wide screens and stack on phones.</p>
      {block.columns.map((col, c) => (
        <fieldset key={c} className="em-column">
          <legend>Column {c + 1}</legend>
          {col.blocks.map((inner, j) => (
            <div key={inner.id ?? j} className="em-inner">
              <div className="em-inner-head">
                <span className="em-outline-kind">{BLOCK_LABEL[inner.type]}</span>
                {!readOnly && (
                  <Button variant="ghost" size="icon" aria-label={`Remove ${BLOCK_LABEL[inner.type].toLowerCase()} from column ${c + 1}`} onClick={() => set(c, col.blocks.filter((_, k) => k !== j))}>
                    <Trash2 size={16} aria-hidden />
                  </Button>
                )}
              </div>
              <BlockFields block={inner} fields={fields} readOnly={readOnly} onChange={(patch) => set(c, col.blocks.map((b, k) => (k === j ? ({ ...b, ...patch } as Block) : b)))} />
            </div>
          ))}
          {!readOnly && (
            <DropdownMenu
              label={`Add to column ${c + 1}`}
              align="start"
              trigger={
                <Button size="sm">
                  <Plus size={16} aria-hidden />
                  Add to column {c + 1}
                </Button>
              }
            >
              {INNER.map((t) => (
                <MenuItem key={t} onSelect={() => set(c, [...col.blocks, newBlock(t)])}>
                  {BLOCK_LABEL[t]}
                </MenuItem>
              ))}
            </DropdownMenu>
          )}
        </fieldset>
      ))}
    </>
  );
}

const COLORS: { key: keyof Style; label: string; fallback: string }[] = [
  { key: "background", label: "Page background", fallback: "#f4f4f5" },
  { key: "content_background", label: "Content background", fallback: "#ffffff" },
  { key: "text_color", label: "Text", fallback: "#18181b" },
  { key: "link_color", label: "Links", fallback: "#2563eb" },
  { key: "button_color", label: "Button", fallback: "#2563eb" },
  { key: "button_text_color", label: "Button text", fallback: "#ffffff" },
];
const DARK: { key: "background" | "content_background" | "text_color" | "link_color"; label: string; fallback: string }[] = [
  { key: "background", label: "Page background", fallback: "#0b0b0e" },
  { key: "content_background", label: "Content background", fallback: "#18181b" },
  { key: "text_color", label: "Text", fallback: "#e4e4e7" },
  { key: "link_color", label: "Links", fallback: "#7aa7ff" },
];

function Swatch({ label, value, disabled, onChange }: { label: string; value: string; disabled?: boolean; onChange: (v: string) => void }) {
  return (
    <label className="em-swatch">
      <input type="color" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
      <span>{label}</span>
      <code>{value}</code>
    </label>
  );
}

function StyleFields({ style, readOnly, onChange }: { style: Style; readOnly?: boolean; onChange: (s: Style) => void }) {
  return (
    <div className="em-fields" role="group" aria-label="Design">
      <Select
        label="Font"
        value={style.font ?? "sans"}
        disabled={readOnly}
        options={[
          { value: "sans", label: "Sans serif (system)" },
          { value: "serif", label: "Serif (Georgia)" },
        ]}
        onValueChange={(v) => onChange({ ...style, font: v as "sans" })}
      />
      <fieldset className="em-column">
        <legend>
          <Sun size={14} aria-hidden /> Light
        </legend>
        {COLORS.map((c) => (
          <Swatch key={c.key} label={c.label} disabled={readOnly} value={(style[c.key] as string) ?? c.fallback} onChange={(v) => onChange({ ...style, [c.key]: v })} />
        ))}
      </fieldset>
      <fieldset className="em-column">
        <legend>
          <Moon size={14} aria-hidden /> Dark mode
        </legend>
        <p className="ui-hint">Mail apps in dark mode use these. Buttons keep their own colors.</p>
        {DARK.map((c) => (
          <Swatch key={c.key} label={c.label} disabled={readOnly} value={style.dark?.[c.key] ?? c.fallback} onChange={(v) => onChange({ ...style, dark: { ...style.dark, [c.key]: v } })} />
        ))}
      </fieldset>
    </div>
  );
}

/** The server's render of the document, refreshed a moment after each change. */
export function PreviewPane({ doc, subject, preheader }: { doc: Doc; subject: string; preheader: string }) {
  const [width, setWidth] = useState<"phone" | "desktop">("desktop");
  const [scheme, setScheme] = useState<"light" | "dark">("light");
  const [view, setView] = useState<"email" | "text">("email");
  const [out, setOut] = useState<Rendered | null>(null);
  const [error, setError] = useState<string>();
  const body = useMemo(() => JSON.stringify({ subject, preheader, document: doc }), [doc, subject, preheader]);
  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      email
        .render(JSON.parse(body))
        .then((r) => live && (setOut(r), setError(undefined)))
        .catch((e) => live && setError(errorText(e)));
    }, 350);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [body]);
  const issues: Issue[] = out ? byLevel(out.issues) : [];
  return (
    <section className="em-preview" aria-label="Preview">
      <div className="em-preview-bar">
        <Segmented
          label="Preview"
          value={view}
          onChange={setView}
          options={[
            { value: "email", label: "Email" },
            { value: "text", label: "Plain text" },
          ]}
        />
        {view === "email" && (
          <>
            <Segmented
              label="Width"
              value={width}
              onChange={setWidth}
              options={[
                { value: "desktop", label: "Desktop", title: "Desktop width" },
                { value: "phone", label: "Phone", title: "Phone width, 375 pixels" },
              ]}
            />
            <Segmented
              label="Color scheme"
              value={scheme}
              onChange={setScheme}
              options={[
                { value: "light", label: "Light" },
                { value: "dark", label: "Dark" },
              ]}
            />
          </>
        )}
        <span className="em-icons" aria-hidden>
          {width === "phone" ? <Smartphone size={14} /> : <Monitor size={14} />}
          {view === "text" ? <Type size={14} /> : <Palette size={14} />}
        </span>
      </div>
      {error ? (
        <p className="em-field-error" role="alert">
          {error}
        </p>
      ) : !out ? (
        <Skeleton className="em-frame-skeleton" />
      ) : view === "text" ? (
        <pre className="em-text-part" tabIndex={0} aria-label="Plain text part">
          {out.text}
        </pre>
      ) : (
        <div className="em-frame-wrap" data-width={width}>
          <iframe
            title={`Email preview, ${width} width, ${scheme} mode`}
            className="em-frame"
            sandbox=""
            srcDoc={out.html}
            style={{ colorScheme: scheme }}
          />
        </div>
      )}
      {out && (
        <div className="em-preview-foot">
          <p className="em-muted">
            Subject: <strong>{out.subject || "(none)"}</strong> &middot; {(out.size / 1024).toFixed(1)} KB
          </p>
          <IssueList issues={issues} compact />
        </div>
      )}
    </section>
  );
}
