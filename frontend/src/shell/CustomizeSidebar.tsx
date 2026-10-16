import { ArrowDown, ArrowUp } from "lucide-react";
import { orderedCore, sidebarPrefs } from "../lib/nav";
import { useStore } from "../lib/store";
import { Button, Dialog, Switch } from "../ui";

export function CustomizeSidebar({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const prefs = useStore(sidebarPrefs);
  const items = orderedCore(prefs);
  const move = (i: number, d: number) => {
    const ids = items.map((x) => x.id);
    [ids[i], ids[i + d]] = [ids[i + d]!, ids[i]!];
    sidebarPrefs.set({ ...prefs, order: ids });
  };
  const toggle = (id: string, show: boolean) =>
    sidebarPrefs.set({ order: items.map((x) => x.id), hidden: show ? prefs.hidden.filter((h) => h !== id) : [...prefs.hidden, id] });

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Customize sidebar"
      description="Show, hide and reorder items. Apps and Settings always stay at the bottom."
      footer={
        <>
          <Button variant="ghost" onClick={() => sidebarPrefs.set({ order: [], hidden: [] })}>
            Reset
          </Button>
          <Button variant="primary" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        </>
      }
    >
      <ul className="sh-custom-list">
        {items.map((it, i) => (
          <li key={it.id} className="sh-custom-row">
            <Switch aria-label={`Show ${it.label}`} checked={!prefs.hidden.includes(it.id)} onCheckedChange={(on) => toggle(it.id, on)} />
            <it.icon size={16} aria-hidden />
            <span className="sh-custom-name">{it.label}</span>
            <Button variant="ghost" size="icon" aria-label={`Move ${it.label} up`} disabled={i === 0} onClick={() => move(i, -1)}>
              <ArrowUp size={16} aria-hidden />
            </Button>
            <Button variant="ghost" size="icon" aria-label={`Move ${it.label} down`} disabled={i === items.length - 1} onClick={() => move(i, 1)}>
              <ArrowDown size={16} aria-hidden />
            </Button>
          </li>
        ))}
      </ul>
    </Dialog>
  );
}
