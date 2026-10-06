import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies to the FastAPI backend; production build is served by FastAPI itself
// (same origin), so the app never needs a hard-coded host.
const backend = process.env.VIGIL_BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": backend,
      "/ws": { target: backend.replace("http", "ws"), ws: true },
    },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
