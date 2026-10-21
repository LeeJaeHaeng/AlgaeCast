// 2부: 장면마다 별도 컨텍스트로 녹화(영상 길이 = 장면 길이, 타이밍 드리프트 없음). scenes.json 에 파일·길이 기록.
// 사용: node record_web.mjs <base_url> <out_dir>
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const [base, outDir] = process.argv.slice(2);
const browser = await chromium.launch({ headless: true });
const HL = `
.demo-hl { outline: 4px solid #38BDF8 !important; outline-offset: 4px; box-shadow: 0 0 0 9999px rgba(10,16,32,0.55) !important; position: relative; z-index: 9999 !important; transition: transform .6s ease; }
.demo-zoom { transform: scale(1.12); transform-origin: left center; }
`;
const scenes = [];
async function scene(name, url, seconds, fn) {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, recordVideo: { dir: outDir, size: { width: 1920, height: 1080 } } });
  const page = await context.newPage();
  await page.goto(url, { waitUntil: "networkidle" });
  await page.addStyleTag({ content: HL }).catch(() => {});
  await page.waitForTimeout(600);
  const t0 = Date.now();
  const hl = async (selector, { zoom = false, ms = 3000 } = {}) => {
    const el = page.locator(selector).first();
    await el.scrollIntoViewIfNeeded().catch(() => {});
    await el.evaluate((e, z) => {
      e.classList.add("demo-hl");
      if (z) e.classList.add("demo-zoom");
    }, zoom).catch(() => {});
    await page.waitForTimeout(ms);
    await el.evaluate((e) => e.classList.remove("demo-hl", "demo-zoom")).catch(() => {});
  };
  await fn(page, hl);
  const rest = seconds * 1000 - (Date.now() - t0);
  if (rest > 0) await page.waitForTimeout(rest);
  await context.close();
  const path = await page.video().path();
  scenes.push({ name, path, seconds });
  console.log(name, path);
}

await scene("main", `${base}/`, 8, async (page) => { await page.mouse.move(960, 540); });
await scene("banner", `${base}/`, 8, async (p, hl) => { await hl('div[role="status"]', { ms: 7200 }); });
await scene("tile", `${base}/`, 10, async (p, hl) => { await hl('a[data-site="2011G56"]', { zoom: true, ms: 9200 }); });
await scene("map", `${base}/`, 6, async (p, hl) => { await hl("section.panel.order-3", { ms: 5200 }); });
await scene("site", `${base}/sites/2011G56`, 8, async (p, hl) => { await hl("section.panel.flex.flex-col.gap-3", { ms: 7200 }); });
await scene("why", `${base}/sites/2011G56`, 8, async (p, hl) => { await hl('section.panel:has(h2:has-text("왜 이렇게 예상했나"))', { ms: 7200 }); });
await scene("history", `${base}/sites/2011G56`, 8, async (p, hl) => {
  await hl('section.panel:has(h2:has-text("지난 녹조 발생 기록"))', { ms: 3600 });
  await hl('section.panel:has(h2:has-text("권고 조치"))', { ms: 3600 });
});
await scene("perf", `${base}/performance`, 8, async (p, hl) => { await hl("div.grid.gap-3.md\\:grid-cols-2", { ms: 7200 }); });
await scene("bars", `${base}/performance`, 8, async (p, hl) => {
  await hl('section.panel:has(h2:has-text("경계 사건을 미리 알린 비율"))', { ms: 3600 });
  await hl('section.panel:has(h2:has-text("시간표"))', { ms: 3600 });
});
await scene("target", `${base}/performance`, 4, async (p, hl) => { await hl('section.panel:has(h2:has-text("원래 목표였던 지표"))', { ms: 3600 }); });
await scene("kiosk", `${base}/?kiosk=1`, 10, async (page) => {
  await page.waitForTimeout(4600);
  await page.goto(`${base}/sites/2011G56?kiosk=1`, { waitUntil: "networkidle" });
});
await scene("score", `${base}/`, 9, async (p, hl) => { await hl('footer[aria-label="성적표"]', { ms: 8200 }); });
await browser.close();
writeFileSync(`${outDir}/scenes.json`, JSON.stringify(scenes, null, 1));
console.log("done");
