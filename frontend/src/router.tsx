import { createBrowserRouter, redirect } from "react-router";
import { CORE } from "./lib/nav";
import { AppsPage } from "./pages/AppsPage";
import { ModulePage } from "./pages/ModulePage";
import { NotFound } from "./pages/NotFound";
import { SettingsPage, SettingsSectionPage } from "./pages/SettingsPage";
import { Shell } from "./shell/Shell";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    HydrateFallback: () => null,
    children: [
      { index: true, loader: () => redirect("/inbox") },
      ...CORE.map((item) => ({ path: item.path.slice(1), element: <ModulePage item={item} /> })),
      { path: "apps", element: <AppsPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "settings/:sectionId", element: <SettingsSectionPage /> },
      // Gallery is lazy so it never weighs on the first load.
      { path: "dev/ui", lazy: async () => ({ Component: (await import("./pages/DevUi")).DevUi }) },
      { path: "*", element: <NotFound /> },
    ],
  },
]);
