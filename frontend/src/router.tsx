import { createBrowserRouter, redirect } from "react-router";
import { RequireAuth } from "./auth/RequireAuth";
import { SignIn } from "./auth/SignIn";
import { CORE, HOME } from "./lib/nav";
import { AppsPage } from "./pages/AppsPage";
import { ModulePage } from "./pages/ModulePage";
import { NotFound } from "./pages/NotFound";
import { SettingsPage, SettingsSectionPage } from "./pages/SettingsPage";

export const router = createBrowserRouter([
  // Public screens, outside the shell.
  { path: "/signin", element: <SignIn /> },
  { path: "/signup", HydrateFallback: () => null, lazy: async () => ({ Component: (await import("./auth/SignUp")).SignUp }) },
  { path: "/auth/magic", HydrateFallback: () => null, lazy: async () => ({ Component: (await import("./auth/MagicLink")).MagicLink }) },
  {
    path: "/",
    element: <RequireAuth />,
    HydrateFallback: () => null,
    children: [
      { index: true, loader: () => redirect(HOME) }, // My Day; the demo opens where its data is, on contacts
      { path: "my-day", lazy: async () => ({ Component: (await import("./tasks/MyDay")).MyDay }) },
      { path: "tasks", lazy: async () => ({ Component: (await import("./tasks/TasksPage")).TasksPage }) },
      { path: "calendar", lazy: async () => ({ Component: (await import("./calendar/CalendarPage")).CalendarPage }) },
      // Contacts is the records area: /contacts, /companies, /deals and custom objects, all one screen (src/records).
      { path: "inbox/:id?", lazy: async () => ({ Component: (await import("./inbox/InboxPage")).InboxPage }) },
      ...CORE.filter((item) => !["inbox", "contacts", "tasks", "calendar", "pipeline"].includes(item.id)).map((item) => ({ path: item.path.slice(1), element: <ModulePage item={item} /> })),
      // The board, its forecast (/pipeline/:id/forecast) and, in the settings, the pipelines and their stages.
      { path: "pipeline/:pipelineId?/:tab?", lazy: async () => ({ Component: (await import("./pipeline/PipelinePage")).PipelinePage }) },
      { path: "contacts/:id?", lazy: async () => ({ Component: (await import("./pages/RecordPages")).ContactsPage }) },
      { path: "companies/:id?", lazy: async () => ({ Component: (await import("./pages/RecordPages")).CompaniesPage }) },
      { path: "deals/:id?", lazy: async () => ({ Component: (await import("./pages/RecordPages")).DealsPage }) },
      { path: "objects/:object/:id?", lazy: async () => ({ Component: (await import("./pages/RecordPages")).ObjectPage }) },
      { path: "apps", element: <AppsPage /> },
      // Forms is lazy too: the builder is large and only needed there.
      { path: "forms", lazy: async () => ({ Component: (await import("./forms/FormsPage")).FormsPage }) },
      { path: "forms/:id", lazy: async () => ({ Component: (await import("./forms/FormBuilder")).FormBuilder }) },
      // Email marketing (module 20): campaigns, templates, sending domains, suppressions and settings.
      { path: "email", lazy: async () => ({ Component: (await import("./email/EmailPage")).CampaignsPage }) },
      { path: "email/campaigns/:id", lazy: async () => ({ Component: (await import("./email/CampaignPage")).CampaignPage }) },
      { path: "email/templates", lazy: async () => ({ Component: (await import("./email/TemplatesPage")).TemplatesPage }) },
      { path: "email/templates/:id", lazy: async () => ({ Component: (await import("./email/TemplatesPage")).TemplateEditor }) },
      { path: "email/domains", lazy: async () => ({ Component: (await import("./email/DomainsPage")).DomainsPage }) },
      { path: "email/suppressions", lazy: async () => ({ Component: (await import("./email/SuppressionsPage")).SuppressionsPage }) },
      { path: "email/settings", lazy: async () => ({ Component: (await import("./email/SuppressionsPage")).EmailSettingsPage }) },
      { path: "settings", element: <SettingsPage /> },
      { path: "settings/channels", lazy: async () => ({ Component: (await import("./inbox/ChannelsSettings")).ChannelsSettings }) },
      { path: "settings/notifications", lazy: async () => ({ Component: (await import("./pages/NotificationSettings")).NotificationSettings }) },
      { path: "settings/pipelines", lazy: async () => ({ Component: (await import("./pipeline/PipelineSettings")).PipelineSettings }) },
      { path: "settings/security", lazy: async () => ({ Component: (await import("./pages/SecuritySettings")).SecuritySettings }) },
      { path: "settings/email", loader: () => redirect("/email/domains") }, // sending domains live with the rest of Email
      { path: "settings/:sectionId", element: <SettingsSectionPage /> },
      // Gallery is lazy so it never weighs on the first load.
      { path: "dev/ui", lazy: async () => ({ Component: (await import("./pages/DevUi")).DevUi }) },
      { path: "*", element: <NotFound /> },
    ],
  },
], { basename: import.meta.env.BASE_URL.replace(/\/$/, "") || "/" });
