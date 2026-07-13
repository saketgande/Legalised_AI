import { chromium } from "playwright";

const BASE = "http://localhost:3000";
const EXE = "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell";

const browser = await chromium.launch({ executablePath: EXE });
const ctx = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  deviceScaleFactor: 1,
  recordVideo: { dir: "/home/user/nda-wedge/video", size: { width: 1280, height: 800 } },
});
const page = await ctx.newPage();

const pause = (ms) => page.waitForTimeout(ms);
async function typeSlow(sel, text) {
  await page.click(sel);
  for (const ch of text) { await page.type(sel, ch, { delay: 45 }); }
}
// smooth-scroll helper so the recording reads like someone reading the page
async function scrollDown(px, steps = 20) {
  for (let i = 0; i < steps; i++) {
    await page.mouse.wheel(0, px / steps);
    await pause(40);
  }
}

// ——— 1. Landing ———
await page.goto(BASE, { waitUntil: "networkidle" });
await pause(1600);

// ——— 2. Requester files an AUTO-lane NDA ———
await page.click('text=I need an NDA');
await page.waitForURL("**/new");
await pause(900);
await typeSlow('input[placeholder="e.g. Acme Corporation"]', "Acme Corporation");
await pause(700);
await page.click('button[type="submit"]');
await page.waitForURL("**/r/**", { timeout: 15000 });
await pause(2200); // show the tracker + "cleared review" banner + activity feed
await scrollDown(300, 12);
await pause(1400);

// ——— 3. Requester files an ASSISTED-lane NDA (long term + foreign law) ———
await page.click('text=Request an NDA');
await page.waitForURL("**/new");
await pause(700);
await typeSlow('input[placeholder="e.g. Acme Corporation"]', "Globex LLC");
await page.selectOption('select >> nth=0', "ONE_WAY");
await pause(300);
await page.selectOption('select >> nth=1', "litigation_support");
await pause(300);
await page.selectOption('select >> nth=2', "EU-DE");
await pause(300);
await page.fill('input[type="number"]', "36");
await pause(800);
await page.click('button[type="submit"]');
await page.waitForURL("**/r/**", { timeout: 15000 });
await pause(2200); // "being reviewed by legal — nothing needed from you"

// ——— 4. Switch to the legal side: the inbox ———
await page.click('text=Legal inbox');
await page.waitForURL("**/inbox");
await pause(2000); // Globex row shows ASSISTED + "2 approvals"

// ——— 5. Open the review cockpit ———
await page.click('tr:has-text("Globex LLC")');
await page.waitForURL("**/review/**", { timeout: 15000 });
await pause(2000);
await scrollDown(700, 24); // read down the assembled NDA
await pause(1200);
await page.mouse.wheel(0, -1400); // back to the top for the ladder
await pause(1200);

// ——— 6. Clear the approval ladder ———
await page.click('button:has-text("Approve as Dana Osei")');
await pause(1600);
await page.click('button:has-text("Approve as Priya Nair")');
await pause(1800);

// ——— 7. Send, then simulate signature ———
await page.click('button:has-text("Approve & send")');
await pause(1800);
await page.click('button:has-text("Simulate counterparty signature")');
await pause(2200); // "Executed and filed" banner

// ——— 8. Back to the requester view — now Signed ———
const url = page.url();
const rid = url.split("/review/")[1];
await page.goto(`${BASE}/r/${rid}`, { waitUntil: "networkidle" });
await pause(2600); // tracker at "Signed", green banner

await ctx.close(); // flush video
await browser.close();
console.log("done");
