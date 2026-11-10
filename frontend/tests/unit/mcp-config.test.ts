// @vitest-environment node
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const config = JSON.parse(readFileSync(join(__dirname, "..", "..", "..", ".mcp.json"), "utf8")) as {
  mcpServers: Record<string, { command: string; args: string[] }>;
};

describe(".mcp.json", () => {
  it("offers Chrome DevTools MCP at an exact version with an isolated profile", () => {
    const server = config.mcpServers["chrome-devtools"];
    expect(server).toBeDefined();
    expect(server.args[0]).toMatch(/^chrome-devtools-mcp@\d+\.\d+\.\d+$/);
    expect(server.args).toContain("--isolated");
  });

  it("keeps Playwright next to it", () => {
    expect(config.mcpServers["playwright"].args).toContain("--isolated");
  });
});
