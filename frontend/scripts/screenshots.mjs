// Capture README screenshots of every page in demo mode (no backend needed).
//
// Usage:  npm run dev            (in another terminal)
//         npm run screenshots    -> ../docs/screenshots/*.png
//
// Env: BASE_URL (default http://localhost:5173)

import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:5173";
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/screenshots");

const PAGES = [
  { file: "session.png",         nav: null,        demo: true },
  { file: "session-signals.png", nav: null,        scrollTo: /signal breakdown/i },
  { file: "analytics.png",       nav: "Analytics" },
  { file: "candidates.png",      nav: "Candidates", select: /#A1B2C3D4/ },
  { file: "models.png",          nav: "Models"    },
];

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  await page.goto(BASE_URL, { waitUntil: "networkidle" });

  for (const p of PAGES) {
    if (p.nav) {
      await page.getByRole("button", { name: p.nav, exact: true }).first().click();
    }
    if (p.demo) {
      await page.getByRole("button", { name: /load demo/i }).first().click();
    }
    if (p.select) {
      await page.getByText(p.select).first().click();
    }
    if (p.scrollTo) {
      const el = page.getByText(p.scrollTo).first();
      await el.evaluate((node) => window.scrollTo(0, node.getBoundingClientRect().top + window.scrollY - 24));
    } else {
      await page.evaluate(() => window.scrollTo(0, 0));
    }
    await page.waitForTimeout(800); // let charts/transitions settle
    await page.screenshot({ path: path.join(OUT, p.file) });
    console.log(`saved ${p.file}`);
  }

  // Dark theme variant of the main view (theme is persisted in localStorage)
  await page.evaluate(() => localStorage.setItem("ts-theme", "dark"));
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: /load demo/i }).first().click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, "session-dark.png") });
  console.log("saved session-dark.png");
  await page.evaluate(() => localStorage.removeItem("ts-theme"));

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
