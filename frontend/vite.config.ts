import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Point the dev server at another API with VITE_API_TARGET=http://127.0.0.1:8031 npm run dev.
const api = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": api } },
});
