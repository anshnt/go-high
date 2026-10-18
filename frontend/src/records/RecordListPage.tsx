import { Filter as FilterIcon, LockKeyhole, MoreHorizontal, Plus, Search, SearchX, Tag as TagIcon, Trash2, TriangleAlert, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useNavigate, useParams, useSearchParams } from "react-router";
import { cn } from "../lib/cn";
import { useMediaQuery } from "../lib/useMediaQuery";
import { useMe } from "../lib/session";
import { PageHeader } from "../shell/PageHeader";
import { TYPING } from "../shell/useShortcuts";
import { Button, DropdownMenu, EmptyState, Input, Kbd, MenuItem, Skeleton, Table, useToast, type Sort } from "../ui";
import { Popover } from "../ui/Popover";
import { Combobox } from "../ui/Combobox";
import { buildColumns, DEFAULT_SORT, defaultColumns } from "./columns";
import { errorMessage, errorStatus } from "./errors.ts";
import { FilterBuilder, FilterChips } from "./FilterBuilder";
import { canonical, countConditions, filterFields } from "./filter.ts";
import { ColumnsMenu, SortMenu } from "./ListMenus";
import { MetaProvider, primeRefs, useFields, useLoadMeta, useMeta } from "./meta.tsx";
import { NewRecordDialog } from "./NewRecordDialog";
import { iconFor, objectPath, recordPath } from "./paths.ts";
import { RecordDetail } from "./RecordDetail";
import { DISPLAY_NAME, nameKey } from "./schema.ts";
import { useRecordsClient, type RecordsClient } from "./client.ts";
import type { FieldDef, Filter, ObjectDef, RecordRow, SavedView, SortSpec } from "./types.ts";
import { useDebounced } from "./useDebounced";
import { useRecordList } from "./useRecordList";
import { ALL_VIEW, ConfirmDialog, SaveViewDialog, ViewTabs } from "./Views";

type Working = { filter: Filter | null; columns: string[]; sort: SortSpec[] };

const lower = (s: string) => s.toLowerCase();
const ensurePrimary = (cols: string[], primary: string) => [primary, ...cols.filter((c) => c !== primary)];

/** One screen for every object: header with views, toolbar, virtualized table, and the record beside it when one is open. */
export function RecordListPage({ object }: { object: string }) {
  const client = useRecordsClient();
  const { meta, error, retry } = useLoadMeta(client);
  if (error) {
    const denied = errorStatus(error) === 403;
    return (
      <div className="rec-page">
        <EmptyState
          icon={denied ? LockKeyhole : TriangleAlert}
          title={denied ? "You do not have access to this" : "We could not load this list"}
          text={denied ? "Ask a workspace admin to give you access." : errorMessage(error)}
          action={denied ? undefined : <Button onClick={retry}>Try again</Button>}
        />
      </div>
    );
  }
  if (!meta) return <ListSkeleton />;
  const def = meta.objects.find((o) => o.key === object);
  if (!def) {
    return (
      <div className="rec-page">
        <EmptyState icon={SearchX} title="We could not find that kind of record" text="It may have been removed from this workspace." />
      </div>
    );
  }
  return (
    <MetaProvider meta={meta}>
      <Loaded key={object} client={client} def={def} />
    </MetaProvider>
  );
}

/** The outline of the page while the workspace's objects and fields load. */
function ListSkeleton() {
  return (
    <div className="rec-page" aria-busy="true" aria-label="Loading">
      <Skeleton style={{ width: 150, height: 26 }} />
      <div className="rec-skel-tabs">
        <Skeleton style={{ width: 96, height: 14 }} />
        <Skeleton style={{ width: 80, height: 14 }} />
        <Skeleton style={{ width: 120, height: 14 }} />
      </div>
      <div className="rec-skel-toolbar">
        <Skeleton style={{ width: 280, height: 32 }} />
        <Skeleton style={{ width: 76, height: 32 }} />
        <Skeleton style={{ width: 96, height: 32 }} />
      </div>
      <div className="rec-skel-table">
        {Array.from({ length: 10 }, (_, i) => (
          <div key={i} className="rec-skel-row">
            <Skeleton style={{ width: 18, height: 18 }} />
            <Skeleton style={{ width: `${18 + ((i * 5) % 12)}%`, height: 12 }} />
            <Skeleton style={{ width: `${22 + ((i * 7) % 14)}%`, height: 12 }} />
            <Skeleton style={{ width: "12%", height: 12 }} />
          </div>
        ))}
      </div>
    </div>
  );
}

function Loaded({ client, def }: { client: RecordsClient; def: ObjectDef }) {
  const meta = useMeta();
  const fields = useFields(def.key);
  const refs = useMemo(() => filterFields(def.key, meta.objects, meta.fields, meta.links), [def.key, meta.objects, meta.fields, meta.links]);
  const navigate = useNavigate();
  const { id: openId } = useParams();
  const [search, setSearch] = useSearchParams();
  const toast = useToast();
  const meId = useMe()?.user.id;
  const noun = lower(def.plural);

  // ---- saved views and the working copy ----
  const [views, setViews] = useState<SavedView[]>([]);
  const [viewsLoaded, setViewsLoaded] = useState(false);
  useEffect(() => {
    let live = true;
    client.listViews(def.key).then(
      (v) => live && (setViews(v), setViewsLoaded(true)),
      () => live && setViewsLoaded(true),
    );
    return () => {
      live = false;
    };
  }, [client, def.key]);
  const viewId = search.get("view") ?? ALL_VIEW;
  const activeView = views.find((v) => v.id === viewId);
  const mine = !!activeView && (!activeView.owner_id || activeView.owner_id === meId);

  // A link to a view that no longer exists falls back to "All" and drops the stale id.
  useEffect(() => {
    if (viewsLoaded && viewId !== ALL_VIEW && !activeView) selectView(ALL_VIEW);
  }, [viewsLoaded, viewId, activeView]); // selectView only edits the URL

  const base = useMemo<Working>(
    () =>
      activeView
        ? { filter: activeView.filter, columns: ensurePrimary(activeView.columns, nameKey(def)), sort: activeView.sort.length ? activeView.sort : DEFAULT_SORT }
        : { filter: null, columns: defaultColumns(def, fields), sort: DEFAULT_SORT },
    [activeView, def, fields],
  );
  const [working, setWorking] = useState<Working>(base);
  // The filter the list actually runs: edits in the builder wait for a pause in typing, everything else applies at once.
  const [filter, setApplied] = useState<Filter | null>(base.filter);
  // Opening another view (or the saved one arriving) replaces the working copy. Done during render so the list never queries twice.
  const baseKey = `${viewId}:${activeView ? "ready" : "none"}`;
  const [seenKey, setSeenKey] = useState(baseKey);
  if (seenKey !== baseKey) {
    setSeenKey(baseKey);
    setWorking(base);
    setApplied(base.filter);
  }
  const dirty = canonical(working.filter) !== canonical(base.filter) || canonical(working.columns) !== canonical(base.columns) || canonical(working.sort) !== canonical(base.sort);

  // ---- the list ----
  const [qText, setQText] = useState("");
  const q = useDebounced(qText.trim(), 250);
  useEffect(() => {
    const t = setTimeout(() => setApplied(working.filter), 250);
    return () => clearTimeout(t);
  }, [working.filter]);
  const waiting = viewId !== ALL_VIEW && !viewsLoaded;
  const list = useRecordList(client, def.key, useMemo(() => ({ filter, sort: working.sort, q }), [filter, working.sort, q]));
  const { rows } = list;
  const rowsRef = useRef(rows);
  rowsRef.current = rows;

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const queryKey = JSON.stringify([filter, working.sort, q]);
  useEffect(() => {
    setSelected(new Set());
    wrapRef.current?.scrollTo({ top: 0 });
  }, [queryKey]);
  useEffect(() => {
    if (openId) setActiveId(openId);
  }, [openId]);

  const [filterOpen, setFilterOpen] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string>();
  const [deleting, setDeleting] = useState<RecordRow[] | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteView, setDeleteView] = useState(false);

  const rail = !!openId;
  const open = useCallback(
    (id: string) => {
      setActiveId(id);
      navigate({ pathname: recordPath(def, id), search: search.toString() ? `?${search}` : "" }, { replace: !!openId });
    },
    [navigate, def, search, openId],
  );
  const close = useCallback(() => navigate({ pathname: objectPath(def), search: search.toString() ? `?${search}` : "" }), [navigate, def, search]);
  const selectView = (id: string) =>
    setSearch(
      (p) => {
        if (id === ALL_VIEW) p.delete("view");
        else p.set("view", id);
        return p;
      },
      { replace: true },
    );

  // ---- keyboard: j k x Enter Esc /, never while typing or with a dialog, menu or list open ----
  const activeRef = useRef(activeId);
  activeRef.current = activeId;
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target as HTMLElement;
      const typing = !!t.closest?.(TYPING);
      const overlay = !!document.querySelector('[role="dialog"], [role="menu"], [role="listbox"]');
      if (e.key === "/" && !typing && !overlay) {
        e.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
        return;
      }
      if (typing || overlay) return;
      const all = rowsRef.current;
      const at = all.findIndex((r) => r.id === activeRef.current);
      if (e.key === "j" || e.key === "k") {
        if (!all.length) return;
        e.preventDefault();
        const next = e.key === "j" ? (at < 0 ? 0 : Math.min(all.length - 1, at + 1)) : Math.max(0, at - 1);
        setActiveId(all[next]!.id);
      } else if (e.key === "x" && at >= 0) {
        e.preventDefault();
        setSelected((s) => {
          const n = new Set(s);
          const id = all[at]!.id;
          if (n.has(id)) n.delete(id);
          else n.add(id);
          return n;
        });
      } else if (e.key === "Enter" && at >= 0 && !t.closest("a, button, [role='checkbox'], [role='tab']")) {
        e.preventDefault();
        open(all[at]!.id);
      } else if (e.key === "Escape") {
        if (openId) close();
        else if (selectedRef.current.size) setSelected(new Set());
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close, openId]);

  // ---- actions ----
  const setFilterNow = (f: Filter | null) => {
    setWorking((w) => ({ ...w, filter: f }));
    setApplied(f);
  };
  const clearAll = () => {
    setFilterNow(null);
    setQText("");
  };
  const discard = () => {
    setWorking(base);
    setApplied(base.filter);
  };

  const saveBody = (w: Working) => ({ object: def.key, filter: w.filter, columns: w.columns, sort: w.sort });
  const saveNew = async (name: string, shared: boolean) => {
    setSaving(true);
    setSaveError(undefined);
    try {
      const v = await client.saveView({ ...saveBody(working), name, shared });
      setViews((vs) => [...vs, v]);
      setSaveOpen(false);
      selectView(v.id);
      toast({ title: "View saved", description: v.name, tone: "success" });
    } catch (e) {
      setSaveError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };
  const updateView = async () => {
    if (!activeView) return;
    try {
      const v = await client.saveView({ ...saveBody(working), id: activeView.id, name: activeView.name, shared: activeView.shared });
      setViews((vs) => vs.map((x) => (x.id === v.id ? v : x)));
      toast({ title: "View updated", description: v.name, tone: "success" });
    } catch (e) {
      toast({ title: "Could not update the view", description: errorMessage(e), tone: "danger" });
    }
  };
  const removeView = async () => {
    if (!activeView) return;
    const gone = activeView;
    try {
      await client.deleteView(gone.id);
      setViews((vs) => vs.filter((x) => x.id !== gone.id));
      setDeleteView(false);
      selectView(ALL_VIEW);
      toast({
        title: "View deleted",
        description: gone.name,
        duration: 8000,
        action: {
          label: "Undo",
          onClick: () => {
            client.saveView({ object: gone.object, name: gone.name, filter: gone.filter, columns: gone.columns, sort: gone.sort, shared: gone.shared }).then(
              (v) => {
                setViews((vs) => [...vs, v]);
                selectView(v.id);
              },
              (e) => toast({ title: "Could not bring the view back", description: errorMessage(e), tone: "danger" }),
            );
          },
        },
      });
    } catch (e) {
      setDeleteView(false);
      toast({ title: "Could not delete the view", description: errorMessage(e), tone: "danger" });
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    const gone = deleting;
    const ids = gone.map((r) => r.id);
    setDeleteBusy(true);
    try {
      await client.remove(def.key, ids);
      list.removeRows(ids);
      // the rest of the list may be on the server still: fetch again when too few rows are left to scroll
      if (list.next && rows.length - ids.length < 40) list.reload();
      setSelected(new Set());
      if (openId && ids.includes(openId)) close();
      const many = ids.length > 1;
      toast({
        title: many ? `${ids.length} ${noun} deleted` : `${def.singular} deleted`,
        description: many ? "They are in the trash for 30 days." : gone[0]!.display_name,
        duration: 8000,
        action: {
          label: "Undo",
          onClick: () => {
            client.restore(def.key, ids).then(
              () => {
                list.reload();
                toast({ title: many ? `${ids.length} ${noun} restored` : `${def.singular} restored`, tone: "success" });
              },
              (e) => toast({ title: "Could not restore", description: errorMessage(e), tone: "danger" }),
            );
          },
        },
      });
    } catch (e) {
      toast({ title: "Could not delete", description: errorMessage(e), tone: "danger" });
    } finally {
      setDeleteBusy(false);
      setDeleting(null);
    }
  };

  const selectedRows = useMemo(() => rows.filter((r) => selected.has(r.id)), [rows, selected]);
  const commonTags = useMemo(() => meta.tags.filter((t) => selectedRows.length > 0 && selectedRows.every((r) => r.tags.some((x) => x.id === t.id))).map((t) => t.id), [meta.tags, selectedRows]);
  const retagSelected = async (next: string[]) => {
    const before = selectedRows;
    const add = next.filter((t) => !commonTags.includes(t));
    const drop = commonTags.filter((t) => !next.includes(t));
    const tagOf = (id: string) => meta.tags.find((t) => t.id === id)!;
    for (const r of before) list.patchRow({ ...r, tags: [...r.tags.filter((t) => !drop.includes(t.id)), ...add.filter((a) => !r.tags.some((t) => t.id === a)).map(tagOf)] });
    const ids = before.map((r) => r.id);
    try {
      for (const t of add) await client.tag(ids, t);
      for (const t of drop) await client.untag(ids, t);
      toast({ title: add.length ? `Tagged ${ids.length} ${ids.length === 1 ? lower(def.singular) : noun}` : `Removed tag from ${ids.length} ${ids.length === 1 ? lower(def.singular) : noun}`, description: [...add, ...drop].map((t) => tagOf(t).name).join(", "), tone: "success" });
    } catch (e) {
      before.forEach((r) => list.patchRow(r));
      toast({ title: "Could not change tags", description: errorMessage(e), tone: "danger" });
    }
  };

  const onChanged = useCallback(
    (row: RecordRow) => {
      list.patchRow(row);
      primeRefs(client, [row]);
    },
    [list.patchRow, client],
  );

  // ---- render ----
  const phone = useMediaQuery("(max-width: 639px)"); // a phone lists two-line rows instead of a table that scrolls sideways
  const columns = useMemo(() => buildColumns(def, fields, working.columns, rail, phone), [def, fields, working.columns, rail, phone]);
  const sort: Sort | undefined = working.sort[0] ? { key: working.sort[0].field, dir: working.sort[0].dir } : undefined;
  const filtered = countConditions(working.filter) > 0 || q !== "";
  const loading = (list.status === "loading" && rows.length === 0) || waiting;
  const refreshing = list.status === "loading" && rows.length > 0;
  const total = list.total;
  const countText =
    loading ? "Loading" : total !== undefined ? `${total.toLocaleString("en-US")} ${total === 1 ? lower(def.singular) : noun}` : `${rows.length.toLocaleString("en-US")}${list.next ? "+" : ""} ${noun}`;

  const empty =
    list.status === "error" ? (
      errorStatus(list.error) === 403 ? (
        <EmptyState icon={LockKeyhole} title={`You do not have access to ${noun}`} text="Ask a workspace admin to give you access." />
      ) : (
        <EmptyState icon={TriangleAlert} title={`We could not load ${noun}`} text={errorMessage(list.error)} action={<Button onClick={list.reload}>Try again</Button>} />
      )
    ) : filtered ? (
      <EmptyState
        icon={SearchX}
        title={`No ${noun} match`}
        text={q ? `Nothing found for "${q}" with these filters.` : "Nothing fits these filters. Try removing one."}
        action={<Button onClick={clearAll}>Clear filters</Button>}
      />
    ) : (
      <EmptyState
        icon={iconFor(def.icon)}
        title={`No ${noun} yet`}
        text={`Add your first ${lower(def.singular)} to start building your list. Every ${lower(def.singular)} gets a timeline, tags and links to other records.`}
        action={
          <Button variant="primary" onClick={() => setNewOpen(true)}>
            <Plus size={16} aria-hidden /> Create {lower(def.singular)}
          </Button>
        }
      />
    );

  const detailFields: FieldDef[] = useMemo(() => fields.filter((f) => f.key !== DISPLAY_NAME), [fields]); // the name is edited through its parts
  const objects = meta.objects;

  return (
    <div className="rec-page" data-open={rail || undefined}>
      <PageHeader
        title={def.plural}
        views={<ViewTabs views={views} active={activeView || viewId === ALL_VIEW ? viewId : ALL_VIEW} dirty={dirty} plural={def.plural} onSelect={selectView} />}
        actions={
          <>
            {objects.length > 1 && (
              <nav className="rec-switch" aria-label="Kinds of record">
                {objects.map((o) => (
                  <NavLink key={o.key} to={objectPath(o)} className="rec-switch-link">
                    {o.plural}
                  </NavLink>
                ))}
              </nav>
            )}
            <Button variant="primary" onClick={() => setNewOpen(true)}>
              <Plus size={16} aria-hidden />
              <span>
                New<span className="rec-hide-sm"> {lower(def.singular)}</span>
              </span>
            </Button>
          </>
        }
      />

      <div className="rec-toolbar" role="toolbar" aria-label={`${def.plural} tools`}>
        <div className="rec-search">
          <Search size={14} aria-hidden className="rec-search-icon" />
          <Input
            ref={searchRef}
            type="search"
            aria-label={`Search ${noun}`}
            placeholder={`Search ${noun}`}
            value={qText}
            onChange={(e) => setQText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.stopPropagation();
                if (qText) setQText("");
                else e.currentTarget.blur();
              }
            }}
            autoComplete="off"
          />
          <span className="rec-search-key" aria-hidden>
            <Kbd>/</Kbd>
          </span>
        </div>

        <Popover
          label="Filters"
          open={filterOpen}
          onOpenChange={setFilterOpen}
          className="rec-fb-pop"
          trigger={
            <Button size="sm" aria-label={`Filter${countConditions(working.filter) ? `, ${countConditions(working.filter)} active` : ""}`}>
              <FilterIcon size={14} aria-hidden />
              <span>Filter</span>
              {countConditions(working.filter) > 0 && <span className="rec-count-pill">{countConditions(working.filter)}</span>}
            </Button>
          }
        >
          <FilterBuilder value={working.filter} refs={refs} total={total} noun={def.plural} onChange={(f) => setWorking((w) => ({ ...w, filter: f }))} />
        </Popover>

        <SortMenu fields={fields} sort={working.sort} onChange={(s) => setWorking((w) => ({ ...w, sort: s }))} />
        {!rail && <ColumnsMenu def={def} fields={fields} columns={working.columns} onChange={(c) => setWorking((w) => ({ ...w, columns: c }))} />}

        <span className="rec-count" aria-live="polite">
          {countText}
        </span>

        <div className="rec-view-actions">
          {dirty && (
            <>
              <span className="rec-unsaved">Unsaved changes</span>
              <Button size="sm" variant="ghost" onClick={discard}>
                Discard
              </Button>
              {activeView && mine && (
                <Button size="sm" variant="primary" onClick={() => void updateView()}>
                  Update view
                </Button>
              )}
              <Button size="sm" variant={activeView && mine ? "secondary" : "primary"} onClick={() => setSaveOpen(true)}>
                {activeView ? "Save as new view" : "Save view"}
              </Button>
            </>
          )}
          {activeView && mine && (
            <DropdownMenu
              label="View options"
              trigger={
                <Button size="icon" variant="ghost" aria-label={`Options for the view ${activeView.name}`}>
                  <MoreHorizontal size={16} aria-hidden />
                </Button>
              }
            >
              <MenuItem icon={<Trash2 size={16} aria-hidden />} onSelect={() => setDeleteView(true)}>
                Delete view
              </MenuItem>
            </DropdownMenu>
          )}
        </div>
      </div>

      <FilterChips value={working.filter} refs={refs} onChange={setFilterNow} onEdit={() => setFilterOpen(true)} />

      {selected.size > 0 && (
        <div className="rec-bulk" role="region" aria-label="Bulk actions">
          <strong>{selected.size.toLocaleString("en-US")} selected</strong>
          <Combobox
            multiple
            label="Tags for selected"
            items={meta.tags.map((t) => ({ value: t.id, label: t.name }))}
            value={commonTags}
            onChange={(ids) => void retagSelected(ids)}
            searchPlaceholder="Search tags"
            trigger={
              <Button size="sm">
                <TagIcon size={14} aria-hidden /> Tag
              </Button>
            }
          />
          <Button size="sm" onClick={() => setDeleting(selectedRows)}>
            <Trash2 size={14} aria-hidden /> Delete
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            <X size={14} aria-hidden /> Clear
          </Button>
        </div>
      )}

      <div className="rec-body" data-open={rail || undefined}>
        <section className="rec-list" aria-label={`${def.plural} list`} data-refreshing={refreshing || undefined}>
          <Table<RecordRow>
            className={cn("rec-table", phone && "rec-table-phone")}
            caption={`${def.plural}, ${countText}`}
            columns={columns}
            rows={rows}
            rowId={(r) => r.id}
            rowLabel={(r) => r.display_name}
            sort={sort}
            onSortChange={(s) => setWorking((w) => ({ ...w, sort: [{ field: s.key, dir: s.dir }] }))}
            selected={selected}
            onSelectedChange={setSelected}
            loading={loading}
            skeletonRows={12}
            empty={rows.length === 0 && (list.status === "error" || (list.status === "ready" && (total !== undefined ? total === 0 : !list.next))) ? empty : null}
            virtual
            activeId={activeId}
            onRowClick={(r) => open(r.id)}
            onEndReached={list.loadMore}
            wrapRef={wrapRef}
            footer={
              list.loadingMore ? (
                <div className="rec-more-row" role="status">
                  Loading more
                </div>
              ) : list.moreFailed ? (
                <div className="rec-more-row">
                  Could not load more. <Button size="sm" variant="ghost" onClick={list.retryMore}>Try again</Button>
                </div>
              ) : null
            }
          />
        </section>

        {openId && (
          <RecordDetail
            key={openId}
            client={client}
            def={def}
            id={openId}
            initial={rows.find((r) => r.id === openId)}
            fields={detailFields}
            onClose={close}
            onChanged={onChanged}
            onDelete={(r) => setDeleting([r])}
          />
        )}
      </div>

      <NewRecordDialog
        client={client}
        def={def}
        fields={fields}
        open={newOpen}
        onOpenChange={setNewOpen}
        onCreated={(row, another) => {
          primeRefs(client, [row]);
          list.reload();
          if (!another) open(row.id);
        }}
      />
      <SaveViewDialog open={saveOpen} onOpenChange={setSaveOpen} onSave={(n, s) => void saveNew(n, s)} busy={saving} error={saveError} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={deleting && deleting.length > 1 ? `Delete ${deleting.length} ${noun}?` : `Delete ${deleting?.[0]?.display_name || lower(def.singular)}?`}
        description="They move to the trash and can be restored for 30 days. You can undo this right after."
        confirm="Delete"
        onConfirm={() => void confirmDelete()}
        busy={deleteBusy}
      />
      <ConfirmDialog
        open={deleteView}
        onOpenChange={setDeleteView}
        title={`Delete the view ${activeView?.name ?? ""}?`}
        description={`The ${noun} in it are not affected.${activeView?.shared ? " Everyone it was shared with loses it." : ""}`}
        confirm="Delete view"
        onConfirm={() => void removeView()}
      />
    </div>
  );
}
