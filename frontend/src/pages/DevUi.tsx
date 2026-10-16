import { Inbox, Plus, Trash2, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { PageHeader } from "../shell/PageHeader";
import {
  Avatar, Badge, Button, Checkbox, Dialog, DropdownMenu, EmptyState, Input, Kbd, MenuItem, MenuLabel, MenuSeparator,
  Select, Sheet, Skeleton, Switch, Table, Tabs, TabsContent, TabsList, TabsTrigger, Textarea, Tooltip, useToast,
  type Column, type Sort,
} from "../ui";
import { Popover } from "../ui/Popover";
import { Combobox } from "../ui/Combobox";

type Row = { id: string; name: string; stage: string; value: number };
const ROWS: Row[] = [
  { id: "c_1042", name: "Ada Lovelace", stage: "Qualified", value: 4200 },
  { id: "c_1043", name: "Grace Hopper", stage: "Proposal", value: 12800 },
  { id: "c_1044", name: "Alan Turing", stage: "New", value: 950 },
  { id: "c_1045", name: "Katherine Johnson", stage: "Won", value: 7300 },
  { id: "c_1046", name: "Margaret Hamilton", stage: "Qualified", value: 5100 },
];
const COLUMNS: Column<Row>[] = [
  { key: "id", header: "Id", mono: true, cell: (r) => r.id },
  { key: "name", header: "Name", sortable: true, cell: (r) => r.name },
  { key: "stage", header: "Stage", cell: (r) => <Badge tone={r.stage === "Won" ? "success" : "neutral"}>{r.stage}</Badge> },
  { key: "value", header: "Value", sortable: true, align: "right", mono: true, cell: (r) => r.value.toLocaleString("en-US") },
];

const Section = ({ title, children }: { title: string; children: ReactNode }) => (
  <section className="dev-section">
    <h2>{title}</h2>
    <div className="dev-row">{children}</div>
  </section>
);

export function DevUi() {
  const toast = useToast();
  const [dialog, setDialog] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [sort, setSort] = useState<Sort>({ key: "name", dir: "asc" });
  const [selected, setSelected] = useState(new Set(["c_1043"]));
  const [on, setOn] = useState(true);
  const [fruit, setFruit] = useState("");
  const [view, setView] = useState("all");
  const [owner, setOwner] = useState<string | null>(null);
  const [tags, setTags] = useState<string[]>(["vip"]);

  const sorted = [...ROWS].sort((a, b) => {
    const x = a[sort.key as keyof Row];
    const y = b[sort.key as keyof Row];
    return (x < y ? -1 : x > y ? 1 : 0) * (sort.dir === "asc" ? 1 : -1);
  });

  return (
    <div className="sh-page dev-gallery">
      <PageHeader
        title="UI gallery"
        description="Every component in its states, for visual review."
        actions={
          <Button variant="primary">
            <Plus size={16} aria-hidden /> New contact
          </Button>
        }
        views={
          <Tabs value={view} onValueChange={setView}>
            <TabsList aria-label="Saved views">
              <TabsTrigger value="all">All contacts</TabsTrigger>
              <TabsTrigger value="mine">Assigned to me</TabsTrigger>
              <TabsTrigger value="new">New this week</TabsTrigger>
            </TabsList>
          </Tabs>
        }
      />

      <Section title="Button">
        <Button variant="primary">Primary</Button>
        <Button>Secondary</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger">
          <Trash2 size={16} aria-hidden /> Delete
        </Button>
        <Button variant="primary" loading>
          Saving
        </Button>
        <Button disabled>Disabled</Button>
        <Button size="sm">Small</Button>
        <Button size="icon" aria-label="Add">
          <Plus size={16} aria-hidden />
        </Button>
      </Section>

      <Section title="Input, Textarea, Select">
        <Input label="Name" placeholder="Ada Lovelace" hint="As it appears on invoices." />
        <Input label="Email" defaultValue="not-an-email" error="Enter a valid email address." />
        <Input label="Disabled" disabled defaultValue="Read only" />
        <Textarea label="Notes" placeholder="Anything worth remembering" />
        <Select
          label="Stage"
          value={fruit}
          onValueChange={setFruit}
          options={[
            { value: "new", label: "New" },
            { value: "qualified", label: "Qualified" },
            { value: "won", label: "Won" },
          ]}
        />
        <Select label="Disabled select" disabled options={[]} />
      </Section>

      <Section title="Checkbox and Switch">
        <Checkbox label="Unchecked" />
        <Checkbox label="Checked" checked onCheckedChange={() => {}} />
        <Checkbox label="Indeterminate" checked="indeterminate" onCheckedChange={() => {}} />
        <Checkbox label="Disabled" disabled />
        <Switch label="Switch" checked={on} onCheckedChange={setOn} />
        <Switch label="Off" checked={false} onCheckedChange={() => {}} />
        <Switch label="Disabled" disabled />
      </Section>

      <Section title="Overlays">
        <Button onClick={() => setDialog(true)}>Open dialog</Button>
        <Button onClick={() => setSheet(true)}>Open sheet</Button>
        <DropdownMenu trigger={<Button>Menu</Button>} align="start">
          <MenuLabel>Contact</MenuLabel>
          <MenuItem>Assign to me</MenuItem>
          <MenuItem>Add tag</MenuItem>
          <MenuItem disabled>Merge (needs two)</MenuItem>
          <MenuSeparator />
          <MenuItem icon={<Trash2 size={16} aria-hidden />}>Move to trash</MenuItem>
        </DropdownMenu>
        <Tooltip content="Tooltips repeat the label">
          <Button variant="ghost">Hover or focus me</Button>
        </Tooltip>
      </Section>

      <Section title="Popover and Combobox">
        <Popover label="Example panel" trigger={<Button>Open a panel</Button>}>
          <p>A panel for forms and lists. It does not dim the page, and Esc closes it.</p>
        </Popover>
        <Combobox
          label="Owner"
          placeholder="Choose an owner"
          value={owner}
          onChange={setOwner}
          onClear={() => setOwner(null)}
          items={[
            { value: "maya", label: "Maya Okafor", hint: "Admin" },
            { value: "theo", label: "Theo Lindqvist" },
            { value: "priya", label: "Priya Raman" },
          ]}
        />
        <Combobox
          multiple
          label="Tags"
          value={tags}
          onChange={setTags}
          items={[
            { value: "vip", label: "VIP", group: "People" },
            { value: "partner", label: "Partner", group: "People" },
            { value: "risk", label: "At risk", group: "Health" },
          ]}
        />
      </Section>

      <Section title="Toast">
        <Button onClick={() => toast({ title: "Saved", description: "Your changes are live.", tone: "success" })}>Success</Button>
        <Button onClick={() => toast({ title: "3 contacts deleted", description: "They are in the trash for 30 days.", action: { label: "Undo", onClick: () => toast({ title: "Restored", tone: "success" }) } })}>With undo</Button>
        <Button onClick={() => toast({ title: "Heads up", description: "This sends 120 SMS (about $0.95)." })}>Info</Button>
        <Button onClick={() => toast({ title: "Could not save", description: "Try again in a moment.", tone: "danger" })}>Error</Button>
      </Section>

      <Section title="Tabs">
        <Tabs defaultValue="a" className="dev-wide">
          <TabsList aria-label="Example tabs">
            <TabsTrigger value="a">Timeline</TabsTrigger>
            <TabsTrigger value="b">Notes</TabsTrigger>
            <TabsTrigger value="c" disabled>
              Files
            </TabsTrigger>
          </TabsList>
          <TabsContent value="a">Messages, calls and events appear here.</TabsContent>
          <TabsContent value="b">Notes appear here.</TabsContent>
        </Tabs>
      </Section>

      <Section title="Badge, Avatar, Kbd, Skeleton">
        <Badge>Neutral</Badge>
        <Badge tone="accent">Accent</Badge>
        <Badge tone="success">Success</Badge>
        <Badge tone="warning">Warning</Badge>
        <Badge tone="danger">Danger</Badge>
        <Badge tone="info">Info</Badge>
        <Avatar name="Ada Lovelace" />
        <Avatar name="Grace Hopper" size="sm" />
        <span>
          <Kbd>Ctrl</Kbd> <Kbd>K</Kbd>
        </span>
        <div className="dev-skeleton">
          <Skeleton style={{ width: "60%" }} />
          <Skeleton style={{ width: "90%" }} />
          <Skeleton style={{ width: "40%" }} />
        </div>
      </Section>

      <Section title="Empty state">
        <div className="dev-card dev-wide">
          <EmptyState
            icon={Users}
            title="No contacts yet"
            text="Import a spreadsheet or add your first contact. Takes about a minute."
            action={<Button variant="primary">Import contacts</Button>}
          />
        </div>
      </Section>

      <Section title="Table: sortable, selectable, sticky header">
        <div className="dev-wide dev-table">
          <Table
            caption="Contacts"
            columns={COLUMNS}
            rows={sorted}
            rowId={(r) => r.id}
            sort={sort}
            onSortChange={setSort}
            selected={selected}
            onSelectedChange={setSelected}
          />
        </div>
      </Section>
      <Section title="Table: loading and empty">
        <div className="dev-wide dev-table">
          <Table caption="Loading" columns={COLUMNS} rows={[]} rowId={(r) => r.id} loading />
        </div>
        <div className="dev-wide">
          <Table
            caption="Empty"
            columns={COLUMNS}
            rows={[]}
            rowId={(r) => r.id}
            empty={<EmptyState icon={Inbox} title="Nothing here" text="No contacts match this view." />}
          />
        </div>
      </Section>

      <Dialog
        open={dialog}
        onOpenChange={setDialog}
        title="Delete 3 contacts?"
        description="They move to trash and can be restored for 30 days."
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialog(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => setDialog(false)}>
              Move to trash
            </Button>
          </>
        }
      >
        <Input label="Type DELETE to confirm" />
      </Dialog>
      <Sheet open={sheet} onOpenChange={setSheet} title="Contact details" description="Opens beside the list on desktop, from the bottom on phones.">
        <Textarea label="Notes" />
      </Sheet>
    </div>
  );
}
