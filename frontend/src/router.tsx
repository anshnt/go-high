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
      // Contacts is the records area: /contacts, /companies, /deals and custom objects, all one screen (src/records).
      ...CORE.filter((item) => item.id !== "contacts" && item.id !== "tasks").map((item) => ({ path: item.path.slice(1), element: <ModulePage item={item} /> })),
      { path: "contacts/:id?", lazy: async () => ({ Component: (await import("./pages/RecordPages")).ContactsPage }) },
      { path: "companies/:id?", lazy: async () => ({ Component: (await import("./pages/RecordPages")).CompaniesPage }) },
      { path: "deals/:id?", lazy: async () => ({ Component: (await import("./pages/RecordPages")).DealsPage }) },
      { path: "objects/:object/:id?", lazy: async () => ({ Component: (await import("./pages/RecordPages")).ObjectPage }) },
      { path: "apps", element: <AppsPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "settings/notifications", lazy: async () => ({ Component: (await import("./pages/NotificationSettings")).NotificationSettings }) },
      { path: "settings/security", lazy: async () => ({ Component: (await import("./pages/SecuritySettings")).SecuritySettings }) },
      { path: "settings/:sectionId", element: <SettingsSectionPage /> },
      // Gallery is lazy so it never weighs on the first load.
      { path: "dev/ui", lazy: async () => ({ Component: (await import("./pages/DevUi")).DevUi }) },
      { path: "*", element: <NotFound /> },
    ],
  },
], { basename: import.meta.env.BASE_URL.replace(/\/$/, "") || "/" });
