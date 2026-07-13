import { chromium } from "playwright";

const OUT = "/home/user/nda-wedge/shots";
const BASE = "http://localhost:3000";
const API = "http://127.0.0.1:8000";

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell' });
const ctx = await browser.newContext({ viewport: { width: 1240, height: 900 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();

async function shot(name) {
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  console.log("shot:", name);
}

// 1. Landing
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await shot("01-landing");

// 2. New request form -> fill an AUTO-lane request (Acme, sales, 24mo)
await page.goto(`${BASE}/new`, { waitUntil: "networkidle" });
await page.fill('input[placeholder="e.g. Acme Corporation"]', "Acme Corporation");
await shot("02-new-form");
await page.click('button[type="submit"]');
await page.waitForURL(`${BASE}/r/**`, { timeout: 10000 });
await shot("03-requester-status-auto");

// 3. Create an ASSISTED request via API so the inbox has a review to do
const assisted = await (await fetch(`${API}/api/requests`, {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify({
    requester_name: "Sam Carter", requester_email: "sam.carter@northwind.example",
    counterparty_name: "Globex LLC", nda_type: "ONE_WAY", purpose: "litigation_support",
    jurisdiction: "EU-DE", term_months: 36,
  }),
})).json();

// 4. Inbox
await page.goto(`${BASE}/inbox`, { waitUntil: "networkidle" });
await shot("04-inbox");

// 5. Review the assisted request (shows ladder + document)
await page.goto(`${BASE}/review/${assisted.id}`, { waitUntil: "networkidle" });
await shot("05-review-assisted");

// 6. Approve both steps, then screenshot the "ready to send" state
for (const s of assisted.ladder.steps) {
  await fetch(`${API}/api/approvals/steps/${s.id}/approve`, {
    method: "POST", headers: { "content-type": "application/json" }, body: "{}",
  });
}
await page.reload({ waitUntil: "networkidle" });
await shot("06-review-approved-ready");

await browser.close();
console.log("done");
