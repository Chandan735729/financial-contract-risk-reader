import { describe, expect, it } from "vitest";
import { loadEnv, readAppEnv } from "./env";

describe("readAppEnv", () => {
  it("falls back to development for unset or unrecognized values", () => {
    expect(readAppEnv(undefined)).toBe("development");
    expect(readAppEnv("staging")).toBe("development");
  });

  it("passes through recognized values", () => {
    expect(readAppEnv("production")).toBe("production");
    expect(readAppEnv("test")).toBe("test");
  });
});

describe("loadEnv", () => {
  it("defaults apiBaseUrl to localhost:8000 when unset", () => {
    const original = process.env.NEXT_PUBLIC_API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    expect(loadEnv().apiBaseUrl).toBe("http://localhost:8000");
    if (original !== undefined) process.env.NEXT_PUBLIC_API_BASE_URL = original;
  });

  it("reads NEXT_PUBLIC_API_BASE_URL when set", () => {
    const original = process.env.NEXT_PUBLIC_API_BASE_URL;
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.example.com";
    expect(loadEnv().apiBaseUrl).toBe("https://api.example.com");
    if (original === undefined) delete process.env.NEXT_PUBLIC_API_BASE_URL;
    else process.env.NEXT_PUBLIC_API_BASE_URL = original;
  });
});
