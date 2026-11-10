// @vitest-environment node
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const appDir = __dirname;

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

const sources = walk(appDir).filter((p) => /\.(ts|tsx)$/.test(p) && !/\.test\.tsx?$/.test(p));
const serverOnly = (p: string) => /[\\/]api[\\/]/.test(p) || /[\\/]lib[\\/]upstream\.ts$/.test(p);
const isClient = (p: string) => readFileSync(p, "utf8").includes('"use client"');
// Built from parts so this file does not itself match the pattern.
const SERVER_ONLY_NAMES = new RegExp(
  ["RELAY_API_KEY", "process\\.", "env", "|API_URL|SIMULATOR_CONTROL_URL|x-api-key"].join(""),
  "i",
);

describe("API key stays on the server (ADR-0009)", () => {
  it("finds source files to check", () => {
    expect(sources.length).toBeGreaterThan(5);
  });

  it("no module reads a NEXT_PUBLIC_ variable", () => {
    for (const p of sources) expect(readFileSync(p, "utf8"), p).not.toMatch(/NEXT_PUBLIC_/);
  });

  it("only server route modules and the upstream helper mention the key or the upstream URLs", () => {
    for (const p of sources.filter((s) => !serverOnly(s))) {
      expect(readFileSync(p, "utf8"), p).not.toMatch(SERVER_ONLY_NAMES);
    }
  });

  it("client components import nothing from the server-only helper", () => {
    for (const p of sources.filter(isClient)) expect(readFileSync(p, "utf8"), p).not.toMatch(/upstream/);
  });

  it("client components call only the frontend's own /api routes", () => {
    const clients = sources.filter(isClient);
    expect(clients.length).toBeGreaterThan(0);
    for (const p of clients) {
      const urls = [...readFileSync(p, "utf8").matchAll(/fetch\(\s*([`"'])(.*?)\1/g)].map((m) => m[2]);
      for (const u of urls) expect(u, p).toMatch(/^\/api\//);
    }
  });
});
