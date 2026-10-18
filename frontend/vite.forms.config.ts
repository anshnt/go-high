import { defineConfig } from "vite";

// The form runtime (src/forms-runtime) as one classic script, dist/embed.js, served at /embed.js: a customer's page loads
// it with a plain <script> tag, so it cannot be a module and cannot share chunks with the app. It runs after the app
// build (`npm run build`) and adds to dist instead of emptying it.
export default defineConfig({
  publicDir: false,
  build: {
    emptyOutDir: false,
    copyPublicDir: false,
    cssCodeSplit: false,
    minify: true,
    lib: { entry: "src/forms-runtime/index.ts", formats: ["iife"], name: "GoHighFormsRuntime", fileName: () => "embed.js" },
  },
});
