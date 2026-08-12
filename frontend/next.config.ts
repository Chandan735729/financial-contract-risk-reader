import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // No `env`/`publicRuntimeConfig` block here on purpose: all public
  // configuration is read exclusively through src/config/env.ts, never
  // scattered across next.config or individual components.
  turbopack: {
    // Pins the workspace root to this package so Turbopack doesn't walk up
    // to an unrelated lockfile outside the git repository.
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
