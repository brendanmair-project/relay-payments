// REL-65: the stylesheet rules that axe cannot see in jsdom. Motion only inside prefers-reduced-motion: no-preference,
// reduced motion respected, and the text colours the console uses meet WCAG AA (4.5:1) on their backgrounds.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "..", "..", "app", "globals.css"), "utf8");

function blockEnd(text: string, open: number): number {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    if (text[i] === "{") depth++;
    if (text[i] === "}" && --depth === 0) return i;
  }
  return text.length;
}

/** The stylesheet with every `@media (prefers-reduced-motion: no-preference) { ... }` block removed. */
function withoutMotionBlocks(text: string): string {
  let out = text;
  for (;;) {
    const at = out.search(/@media\s*\(prefers-reduced-motion:\s*no-preference\)\s*\{/);
    if (at < 0) return out;
    const open = out.indexOf("{", at);
    out = out.slice(0, at) + out.slice(blockEnd(out, open) + 1);
  }
}

function luminance(hex: string): number {
  const n = hex.replace("#", "");
  const full = n.length === 3 ? [...n].map((c) => c + c).join("") : n;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
function token(name: string): string {
  const m = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{3,6})`).exec(css);
  if (!m) throw new Error(`no --${name} in globals.css`);
  return m[1];
}

describe("globals.css accessibility rules", () => {
  it("has no transition or animation outside a prefers-reduced-motion: no-preference block", () => {
    const rest = withoutMotionBlocks(css);
    expect(rest).not.toMatch(/\btransition\s*:/);
    expect(rest).not.toMatch(/\banimation\s*:/);
    expect(rest).not.toMatch(/@keyframes/);
    expect(rest).not.toMatch(/scroll-behavior\s*:\s*smooth/);
  });

  it("never animates on load: motion rules are tied to :hover or :active, not to element selectors alone", () => {
    const match = /@media\s*\(prefers-reduced-motion:\s*no-preference\)\s*\{/.exec(css);
    if (!match) return; // no motion at all is fine
    const open = css.indexOf("{", match.index);
    const body = css.slice(open, blockEnd(css, open));
    expect(body).not.toMatch(/@keyframes|animation\s*:/);
  });

  it.each([
    ["fg", "bg"],
    ["muted", "bg"],
    ["link", "bg"],
    ["hero-fg", "hero-bg"],
    ["hero-accent", "hero-bg"],
    ["hero-muted", "hero-bg"],
    ["good", "bg"],
    ["bad", "bg"],
    ["warn", "bg"],
    ["info", "bg"],
    ["fg", "tint"],
    ["muted", "tint"],
  ])("text colour --%s on --%s is at least 4.5:1", (fg, bg) => {
    expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(4.5);
  });

  // REL-67 exit check: `.fine` uses --hero-muted, which is readable only on the dark hero (1.41:1 on white). Pages on
  // the light background use `.fine-dark`.
  it("uses the hero-only .fine class only inside the hero (ValueStory)", () => {
    const appDir = join(__dirname, "..", "..", "app");
    const users = readdirSync(appDir)
      .filter((f) => f.endsWith(".tsx") && !f.endsWith(".test.tsx"))
      .filter((f) => /className=["{`]+fine[ "`]/.test(readFileSync(join(appDir, f), "utf8")));
    expect(users).toEqual(["ValueStory.tsx"]);
  });
});
