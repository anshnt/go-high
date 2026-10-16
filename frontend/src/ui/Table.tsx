import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import type { ReactNode } from "react";
import { Checkbox } from "./Toggle";
import { Skeleton } from "./Display";

export type Column<T> = {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  sortable?: boolean;
  align?: "right";
  /** ids, codes, numbers */
  mono?: boolean;
};
export type Sort = { key: string; dir: "asc" | "desc" };

type Props<T> = {
  columns: Column<T>[];
  rows: T[];
  rowId: (row: T) => string;
  caption: string;
  sort?: Sort;
  onSortChange?: (s: Sort) => void;
  selected?: Set<string>;
  onSelectedChange?: (s: Set<string>) => void;
  loading?: boolean;
  empty?: ReactNode;
};

export function Table<T>({ columns, rows, rowId, caption, sort, onSortChange, selected, onSelectedChange, loading, empty }: Props<T>) {
  const selectable = !!selected && !!onSelectedChange;
  const ids = rows.map(rowId);
  const all = selectable && ids.length > 0 && ids.every((id) => selected.has(id));
  const some = selectable && ids.some((id) => selected.has(id));
  const toggle = (id: string, on: boolean) => {
    const next = new Set(selected);
    if (on) next.add(id);
    else next.delete(id);
    onSelectedChange?.(next);
  };
  const nextSort = (key: string): Sort => ({ key, dir: sort?.key === key && sort.dir === "asc" ? "desc" : "asc" });

  return (
    <div className="ui-table-wrap">
      <table className="ui-table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {selectable && (
              <th className="ui-th-check">
                <Checkbox
                  aria-label="Select all rows"
                  checked={all ? true : some ? "indeterminate" : false}
                  onCheckedChange={(on) => onSelectedChange?.(on ? new Set(ids) : new Set())}
                />
              </th>
            )}
            {columns.map((c) => (
              <th
                key={c.key}
                data-align={c.align}
                aria-sort={sort?.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : c.sortable ? "none" : undefined}
              >
                {c.sortable ? (
                  <button type="button" className="ui-sort" onClick={() => onSortChange?.(nextSort(c.key))}>
                    {c.header}
                    {sort?.key === c.key ? sort.dir === "asc" ? <ArrowUp size={14} aria-hidden /> : <ArrowDown size={14} aria-hidden /> : <ChevronsUpDown size={14} aria-hidden />}
                  </button>
                ) : (
                  c.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody aria-busy={loading || undefined}>
          {loading
            ? Array.from({ length: 4 }, (_, i) => (
                <tr key={i}>
                  {selectable && <td />}
                  {columns.map((c) => (
                    <td key={c.key}>
                      <Skeleton style={{ width: `${55 + ((i + c.key.length) % 4) * 10}%` }} />
                    </td>
                  ))}
                </tr>
              ))
            : rows.map((r) => {
                const id = rowId(r);
                return (
                  <tr key={id} data-selected={selected?.has(id) || undefined}>
                    {selectable && (
                      <td className="ui-th-check">
                        <Checkbox aria-label={`Select row ${id}`} checked={selected.has(id)} onCheckedChange={(on) => toggle(id, on)} />
                      </td>
                    )}
                    {columns.map((c) => (
                      <td key={c.key} data-align={c.align} className={c.mono ? "mono" : undefined}>
                        {c.cell(r)}
                      </td>
                    ))}
                  </tr>
                );
              })}
        </tbody>
      </table>
      {!loading && rows.length === 0 && empty}
    </div>
  );
}
