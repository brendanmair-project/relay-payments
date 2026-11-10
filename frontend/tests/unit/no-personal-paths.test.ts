// @vitest-environment node
// REL-61: no tracked text file holds a machine path into a Windows user folder or the owner's email address, so the
// repository can be published as it is. Patterns are built from parts so this file does not match itself.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const root = join(__dirname, "..", "..", "..");
const gitAvailable = existsSync(join(root, ".git"));

function git(args: string[]): string {
  return execFileSync("git", args, { cwd: root, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
}

const slash = "[\\\\/]+";
const drive = "[A-Za-z]:";
const users = "Us" + "ers";
const patterns: [string, RegExp][] = [
  ["Windows user folder path", new RegExp(`${drive}${slash}${users}${slash}[^\\s\\\\/"'\`]+`, "i")],
  ["Git Bash user folder path", new RegExp(`(^|[^A-Za-z0-9_.-])/[A-Za-z]/${users}/[^\\s/"'\`]+`, "i")],
];

function trackedTextFiles(): { path: string; text: string }[] {
  const files = git(["ls-files", "-z"]).split("\0").filter(Boolean);
  const out: { path: string; text: string }[] = [];
  for (const f of files) {
    const full = join(root, f);
    if (!existsSync(full)) continue;
    const buf = readFileSync(full);
    if (buf.includes(0)) continue; // binary
    out.push({ path: f, text: buf.toString("utf8") });
  }
  return out;
}

describe.skipIf(!gitAvailable)("tracked files carry no personal paths or address", () => {
  const files = gitAvailable ? trackedTextFiles() : [];

  it("finds tracked files", () => {
    expect(files.length).toBeGreaterThan(50);
  });

  it("holds no absolute path into a Windows user folder", () => {
    const hits: string[] = [];
    for (const f of files) {
      for (const [label, re] of patterns) {
        const m = re.exec(f.text);
        if (m) hits.push(`${f.path}: ${label}`);
      }
    }
    expect(hits).toEqual([]);
  });

  it("holds not the address from git config user.email", () => {
    let address = "";
    try {
      address = git(["config", "user.email"]).trim();
    } catch {
      address = "";
    }
    if (!address) return; // nothing to check against on this machine
    const needle = address.toLowerCase();
    const hits = files.filter((f) => f.text.toLowerCase().includes(needle)).map((f) => f.path);
    expect(hits).toEqual([]);
  });
});
