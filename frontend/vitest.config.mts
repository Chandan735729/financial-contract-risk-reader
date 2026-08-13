import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src"),
    },
  },
  test: {
    // jsdom, not "node" -- Phase 9 adds component tests that render real
    // DOM (React Testing Library). jsdom is a superset for the existing
    // plain-logic tests (env.test.ts, clauseAnalysis.test.ts): they don't
    // depend on the *absence* of a DOM, so this is a safe global switch
    // rather than a per-file environment split.
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
