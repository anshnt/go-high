import { createBrowserRouter, redirect } from "react-router";
import { RequireAuth } from "./auth/RequireAuth";
import { SignIn } from "./auth/SignIn";
import { CORE } from "./lib/nav";
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
      { index: true, loader: () => redirect("/inbox") },
      ...CORE.map((item) => ({ path: item.path.slice(1), element: <ModulePage item={item} /> })),
      { path: "apps", element: <AppsPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "settings/security", lazy: async () => ({ Component: (await import("./pages/SecuritySettings")).SecuritySettings }) },
      { path: "settings/:sectionId", element: <SettingsSectionPage /> },
      // Gallery is lazy so it never weighs on the first load.
      { path: "dev/ui", lazy: async () => ({ Component: (await import("./pages/DevUi")).DevUi }) },
      { path: "*", element: <NotFound /> },
    ],
  },
]);
