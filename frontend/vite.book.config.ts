import { readFileSync } from "node:fs";
import { defineConfig } from "vite";

// The booking page and widget (src/book) as one classic script, dist/book/book.js, served at /book/book.js: a customer's
// site loads it with a plain <script> tag, so it cannot be a module and cannot share chunks with the app. Beside it go
// page.html (what /book/... and /booking/... serve) and the Geist font the page uses. It runs after the app build
// (`npm run build`) and adds to dist instead of emptying it.
export default defineConfig({
  publicDir: false,
  plugins: [
    {
      name: "booking-page",
      generateBundle() {
        this.emitFile({ type: "asset", fileName: "page.html", source: readFileSync("src/book/page.html", "utf8") });
        this.emitFile({ type: "asset", fileName: "geist.woff2", source: readFileSync("node_modules/@fontsource-variable/geist/files/geist-latin-wght-normal.woff2") });
      },
    },
  ],
  build: {
    outDir: "dist/book",
    emptyOutDir: false,
    copyPublicDir: false,
    cssCodeSplit: false,
    minify: true,
    lib: { entry: "src/book/index.ts", formats: ["iife"], name: "GoHighBooking", fileName: () => "book.js" },
  },
});
