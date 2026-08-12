// Typed frontend configuration — single point of access to environment
// variables. No other frontend module should read `process.env` directly
// (see next.config.ts and frontend/.env.example).
//
// Only `NEXT_PUBLIC_*` variables are readable in the browser bundle, and
// only such variables belong here — backend secrets (ANTHROPIC_API_KEY,
// DATABASE_URL) must never be defined with a NEXT_PUBLIC_ prefix or read
// from this module.

export interface AppEnv {
  apiBaseUrl: string;
  appEnv: "development" | "test" | "production";
}

export function readAppEnv(raw: string | undefined): AppEnv["appEnv"] {
  if (raw === "production" || raw === "test") {
    return raw;
  }
  return "development";
}

export function loadEnv(): AppEnv {
  return {
    apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
    appEnv: readAppEnv(process.env.NEXT_PUBLIC_APP_ENV),
  };
}

export const env: AppEnv = loadEnv();
