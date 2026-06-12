import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    sourcemap: true,
    // RFC 0011 Phase C3 (2026-05-08): split out reactflow (only the
    // DAG editor route uses it) so the rest of the app doesn't pay
    // for ~90kB on every page load. The remaining vendor code stays
    // co-located with rollup's default heuristic — splitting antd
    // out introduces circular chunks because it imports React, which
    // is shared with everything else.
    //
    // The bigger win (route-level lazy splits via React.lazy) is a
    // follow-up; documented in RFC 0011 §6 for a Phase C4.
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("/reactflow/") || id.includes("@reactflow/")) {
            return "vendor-reactflow";
          }
          return undefined;
        },
      },
    },
    // 1.5 MB is the practical floor for an antd-based admin app
    // until we route-split. Bump warn limit so the build doesn't
    // emit noisy warnings when the bundle is within expectations.
    chunkSizeWarningLimit: 1700,
  },
  server: {
    host: "0.0.0.0",
    port: 3000,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
        timeout: 120_000,
      },
      "/ws": {
        target: process.env.VITE_WS_TARGET || "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
