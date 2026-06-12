/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/__tests__/setup.ts"],
    include: ["src/__tests__/**/*.test.{ts,tsx}"],
    globals: true,
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "json-summary"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/__tests__/**", "src/vite-env.d.ts"],
      // RFC 0009 P0-C (2026-05-08) / RFC 0011 G3 (2026-05-08):
      // pin no-regression floors at the current measured baselines.
      //
      // 2026-05-09 — fork-trim adjustment: ai-trading removed two
      // orphan vitest files (CodingSessionDetail / CodingSessionList)
      // whose page modules the fork deleted. CI re-measured at:
      //   10.99 % statements / 8.4 % branches / 7.42 % functions /
      //   12.06 % lines.
      // Floors set marginally below actual to absorb test-flake noise
      // but tight enough that new uncovered code drops the gate.
      // Cleanup PRs that ADD covered code ratchet these up; new
      // uncovered code cannot sneak in.
      thresholds: {
        statements: 10,
        branches: 8,
        functions: 7,
        lines: 12,
      },
    },
  },
});
