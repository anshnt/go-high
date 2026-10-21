import {
  CalendarDays,
  Inbox,
  Kanban,
  LayoutGrid,
  ListChecks,
  Settings,
  Sunrise,
  Users,
  Workflow,
  ChartColumn,
  Globe,
  Mail,
  CreditCard,
  Share2,
  Star,
  GraduationCap,
  FileText,
  LifeBuoy,
  ShoppingBag,
  Megaphone,
  Handshake,
  Newspaper,
  MapPin,
  Image,
  Building2,
  ClipboardList,
  type LucideIcon,
} from "lucide-react";
import { persisted } from "./store";

export type NavItem = { id: string; label: string; path: string; icon: LucideIcon; gKey?: string; blurb: string; /** other places that belong to this item, so it stays highlighted there */ also?: string[] };

export const inArea = (item: NavItem, pathname: string) => [item.path, ...(item.also ?? [])].some((p) => pathname === p || pathname.startsWith(`${p}/`));

// The small default core. Order here is the default sidebar order.
export const CORE: NavItem[] = [
  { id: "inbox", label: "Inbox", path: "/inbox", icon: Inbox, gKey: "i", blurb: "Every conversation from SMS, email, calls and chat in one place, assigned and answered fast." },
  { id: "contacts", label: "Contacts", path: "/contacts", also: ["/companies", "/deals", "/objects"], icon: Users, gKey: "c", blurb: "People and companies with custom fields, tags, a full timeline and saved views." },
  { id: "pipeline", label: "Pipeline", path: "/pipeline", icon: Kanban, gKey: "p", blurb: "Deals on a board you can drag, with stages, values and clear next steps." },
  { id: "calendar", label: "Calendar", path: "/calendar", icon: CalendarDays, gKey: "k", blurb: "Booking pages, team availability and appointments synced with Google and Microsoft." },
  { id: "tasks", label: "Tasks", path: "/tasks", icon: ListChecks, gKey: "t", blurb: "To-dos on any record, with due dates, owners, repeats and a board and calendar view." },
  { id: "automations", label: "Automations", path: "/automations", icon: Workflow, gKey: "a", blurb: "Visual workflows that follow up, route leads and update records while you sleep." },
  { id: "reports", label: "Reports", path: "/reports", icon: ChartColumn, gKey: "r", blurb: "Dashboards for leads, revenue and response times, with shareable saved views." },
];

// Where signing in lands, above the core items. A demo build (VITE_DEMO=1) has no tasks to show, so it opens on contacts.
export const MY_DAY_NAV: NavItem = { id: "my-day", label: "My Day", path: "/my-day", icon: Sunrise, gKey: "m", blurb: "Your tasks, appointments and conversations for today in one list." };
export const HOME = import.meta.env.VITE_DEMO === "1" ? "/contacts" : MY_DAY_NAV.path;

export const APPS_NAV: NavItem = { id: "apps", label: "Apps", path: "/apps", icon: LayoutGrid, blurb: "Switch on only the modules you need." };
export const SETTINGS_NAV: NavItem = { id: "settings", label: "Settings", path: "/settings", icon: Settings, blurb: "One searchable hub for every setting." };

export type AppInfo = { id: string; label: string; icon: LucideIcon; blurb: string; path?: string };

// An app with a path is built and can be switched on; the rest still say "Coming soon".
export const APPS: AppInfo[] = [
  { id: "forms", label: "Forms", icon: ClipboardList, path: "/forms", blurb: "Forms, surveys and quizzes with branching, scoring and embeds that create contacts." },
  { id: "sites", label: "Sites and funnels", icon: Globe, blurb: "Build fast pages and funnels that publish as static HTML." },
  { id: "email", label: "Email marketing", icon: Mail, path: "/email", blurb: "Campaigns and newsletters with deliverability checks built in." },
  { id: "payments", label: "Payments", icon: CreditCard, blurb: "Invoices, subscriptions and payment links with a clear cost preview." },
  { id: "social", label: "Social planner", icon: Share2, blurb: "Plan and publish posts across your social accounts." },
  { id: "reputation", label: "Reputation", icon: Star, blurb: "Ask for reviews and reply to them from one queue." },
  { id: "courses", label: "Courses", icon: GraduationCap, blurb: "Courses, memberships and communities for your customers." },
  { id: "documents", label: "Documents", icon: FileText, blurb: "Proposals, contracts and e-signatures tied to deals." },
  { id: "helpdesk", label: "Helpdesk", icon: LifeBuoy, blurb: "Tickets and a help centre that share the inbox." },
  { id: "store", label: "Store", icon: ShoppingBag, blurb: "Sell products with carts, orders and fulfilment." },
  { id: "ads", label: "Ads", icon: Megaphone, blurb: "Track ad spend and send conversions back to ad platforms." },
  { id: "affiliates", label: "Affiliates", icon: Handshake, blurb: "Referral programs with tracked links and payouts." },
  { id: "blogs", label: "Blogs", icon: Newspaper, blurb: "Publish articles that bring in search traffic." },
  { id: "listings", label: "Listings", icon: MapPin, blurb: "Keep business listings accurate and find local prospects." },
  { id: "media", label: "Media library", icon: Image, blurb: "One place for images, files and your brand kit." },
  { id: "portal", label: "Client portal", icon: Building2, blurb: "A branded space where clients see their work and pay." },
];

export type SettingsSection = { id: string; label: string; blurb: string; keywords: string };

export const SETTINGS: SettingsSection[] = [
  { id: "profile", label: "Profile", blurb: "Your name, photo, password and sign-in methods.", keywords: "account password 2fa avatar" },
  { id: "workspace", label: "Workspace", blurb: "Business name, time zone, currency and hours.", keywords: "business timezone company" },
  { id: "team", label: "Team and roles", blurb: "Invite people and control what each role can see.", keywords: "users permissions invite" },
  { id: "billing", label: "Billing and usage", blurb: "Plan, wallet balance and a clear view of usage costs.", keywords: "invoice plan wallet credits" },
  { id: "channels", label: "Channels", blurb: "Connect SMS, email, WhatsApp and web chat accounts, and the web chat widget.", keywords: "inbox sms email whatsapp webchat twilio telnyx smtp mailgun widget provider webhook" },
  { id: "phone", label: "Phone and SMS", blurb: "Numbers, sender registration and quiet hours.", keywords: "a2p twilio text calling" },
  { id: "email", label: "Email and domains", blurb: "Sending domains, SPF, DKIM and mailbox connections.", keywords: "dns dkim spf deliverability" },
  { id: "calendars", label: "Calendars", blurb: "Availability, booking rules and connected calendars.", keywords: "booking google outlook" },
  { id: "pipelines", label: "Pipelines", blurb: "Stages, win reasons and deal rules.", keywords: "deals stages" },
  { id: "fields", label: "Custom fields and tags", blurb: "Fields and tags that shape your records.", keywords: "properties labels" },
  { id: "notifications", label: "Notifications", blurb: "Choose what pings you and where, and when it stays quiet.", keywords: "alerts push email digest quiet hours" },
  { id: "integrations", label: "Integrations", blurb: "Connect other tools to this workspace.", keywords: "connect oauth zapier" },
  { id: "api", label: "API and webhooks", blurb: "Private tokens, webhooks and event logs.", keywords: "developer token key" },
  { id: "security", label: "Security", blurb: "Two-factor, sessions and IP rules.", keywords: "2fa sessions ip" },
  { id: "setup", label: "Setup health", blurb: "A live checklist of what is verified and what needs a fix.", keywords: "checklist dns verification" },
  { id: "audit", label: "Audit log", blurb: "Who changed what and when.", keywords: "history activity" },
  { id: "data", label: "Import and export", blurb: "Bring data in, take it out, with a preview and undo.", keywords: "csv migrate backup" },
];

// ponytail: sidebar order and visibility live in localStorage; they move server-side
// (per user and per role) once auth (#2) lands.
export type SidebarPrefs = { order: string[]; hidden: string[] };
const isIds = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");
export const sidebarPrefs = persisted<SidebarPrefs>("gh:sidebar", { order: [], hidden: [] }, (v) => {
  const p = v as Partial<SidebarPrefs> | null;
  return p && isIds(p.order) && isIds(p.hidden) ? { order: p.order, hidden: p.hidden } : undefined;
});

// ponytail: which apps are on lives in localStorage, like the sidebar; it moves to workspace settings with them. Forms and
// Email are on by default for now.
export const appsOn = persisted<string[]>("gh:apps", ["forms", "email"], (v) => (isIds(v) ? v : undefined));

/** The apps that are built and switched on, as sidebar items. */
export const enabledApps = (on: string[]): NavItem[] =>
  APPS.flatMap((a) => (a.path && on.includes(a.id) ? [{ id: a.id, label: a.label, path: a.path, icon: a.icon, blurb: a.blurb }] : []));

/** Core items in the user's order. Unknown or new ids fall back to the default order. */
export function orderedCore(prefs: SidebarPrefs): NavItem[] {
  const rank = (id: string) => {
    const i = prefs.order.indexOf(id);
    return i < 0 ? 1000 + CORE.findIndex((c) => c.id === id) : i;
  };
  return [...CORE].sort((a, b) => rank(a.id) - rank(b.id));
}

export const visibleCore = (prefs: SidebarPrefs) => orderedCore(prefs).filter((c) => !prefs.hidden.includes(c.id));
