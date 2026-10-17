import { chromium } from "playwright";

const input = process.argv[2] || "https://kodamantv21.com/";
const start = new URL(input);
const allowedHost = /^kodamantv\d+\.com$/i;
if (start.protocol !== "https:" || !allowedHost.test(start.hostname)) {
  throw new Error("Only HTTPS kodamantv<N>.com public pages are allowed");
}

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  // Dismiss native JS dialogs so a provider warning cannot block menu refresh.
  page.on("dialog", (dialog) => dialog.dismiss().catch(() => {}));
  await page.goto(`${start.origin}/`, { waitUntil: "domcontentloaded", timeout: 45_000 });
  await page.locator("#next-tab").waitFor({ state: "attached", timeout: 20_000 });
  // This is the same visible KANALLAR tab a visitor clicks; force bypasses ad overlays.
  await page.locator("#next-tab").click({ force: true });
  await page.waitForFunction(() => {
    const menu = document.querySelector("#channels-content");
    if (!menu) return false;
    return Array.from(menu.querySelectorAll('a[href*="channel?id="]')).some((link) => {
      const style = getComputedStyle(link);
      const rect = link.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && style.display !== "none" &&
        style.visibility !== "hidden" && Number(style.opacity || 1) > 0 &&
        !link.closest('[hidden], [aria-hidden="true"]');
    });
  }, null, { timeout: 30_000 });

  const channels = await page.locator('#channels-content a[href*="channel?id="]').evaluateAll((links) =>
    links.filter((link) => {
      const style = getComputedStyle(link);
      const rect = link.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && style.display !== "none" &&
        style.visibility !== "hidden" && Number(style.opacity || 1) > 0 &&
        !link.closest('[hidden], [aria-hidden="true"]');
    }).map((link) => ({
      name: link.innerText.replace(/\s+/g, " ").trim(),
      href: link.getAttribute("href") || "",
    }))
  );
  const finalUrl = new URL(page.url());
  if (finalUrl.protocol !== "https:" || !allowedHost.test(finalUrl.hostname)) {
    throw new Error("The visible menu redirected outside the numbered Kodaman domain family");
  }
  if (!channels.length || channels.length > 100) {
    throw new Error(`Unexpected public KANALLAR menu size: ${channels.length}`);
  }
  process.stdout.write(JSON.stringify({ base_url: finalUrl.origin, channels }));
} finally {
  await browser.close();
}
