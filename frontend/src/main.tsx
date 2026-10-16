import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router/dom";
import "./styles/tokens.css";
import "./styles/base.css";
import "./lib/prefs";
import { ToastProvider, TooltipProvider } from "./ui"; // loads ui.css before shell.css
import "./shell/shell.css";
import { router } from "./router";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <TooltipProvider>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </TooltipProvider>
  </StrictMode>,
);
