import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Point the dev server at another API with VITE_API_TARGET=http://127.0.0.1:8031 npm run dev.
const api = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  // The public demo is served from GitHub Pages under /go-high/.
  base: process.env.VITE_DEMO === "1" ? "/go-high/" : "/",
  // public/ holds the image of the demo's sample email (src/lib/demoInboxData.ts), which the real app has no use for.
  publicDir: process.env.VITE_DEMO === "1" ? "public" : false,
  // /f/KEY (the hosted form page), /embed.js (the form runtime) and the booking pages (/book/..., /booking/...) also come
  // from the API, which serves them from the built web app.
  server: { port: 5173, proxy: { "/api": api, "^/f/.*": api, "/embed.js": api, "^/book(ing)?/.*": api } },
});
