// 2부(v7, 2026-10-28 T24 전환): 장면마다 별도 컨텍스트로 녹화(헤드리스 Chromium, 영상 길이 = 장면 길이).
// v5(record_web.mjs) 대비: banner·history 8→6초, map 6→4초, 다시 보기 장면 ①(강정·고령 2026-07-27, 띠 '사후 계산' 문구) 6초 추가
// — 전체 길이 2:28 유지. 장면마다 화면 글자(innerText)를 texts.json 에 남겨 옛 문구 검사에 쓴다.
// 사용: node record_web_v7.mjs <base_url> <out_dir> [장면 이름,쉼표 구분 — 주면 그 장면만 녹화]
// 다시 보기 장면 ①은 위 띠를 1.7배로 키워(왼쪽 위 기준) '사후 계산' 문구가 읽히게 한다.
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const [base, outDir, only] = process.argv.slice(2);
const pick = only ? new Set(only.split(",")) : null;
const browser = await chromium.launch({ headless: true });
const HL = `
.demo-hl { outline: 4px solid #38BDF8 !important; outline-offset: 4px; box-shadow: 0 0 0 9999px rgba(10,16,32,0.55) !important; position: relative; z-index: 9999 !important; transition: transform .6s ease; }
.demo-zoom { transform: scale(1.12); transform-origin: left center; }
`;
const scenes = [];
const texts = {};
async function scene(name, url, seconds, fn) {
  if (pick && !pick.has(name)) return;
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, recordVideo: { dir: outDir, size: { width: 1920, height: 1080 } } });
  const page = await context.newPage();
  await page.goto(url, { waitUntil: "networkidle" });
  await page.addStyleTag({ content: HL }).catch(() => {});
  await page.waitForTimeout(600);
  const t0 = Date.now();
  const hl = async (selector, { zoom = false, scale = 0, ms = 3000 } = {}) => {
    const el = page.locator(selector).first();
    await el.scrollIntoViewIfNeeded().catch(() => {});
    await el.evaluate((e, [z, s]) => {
      e.classList.add("demo-hl");
      if (z) e.classList.add("demo-zoom");
      if (s) {
        e.style.transformOrigin = "left top";
        e.style.transform = `scale(${s})`;
      }
    }, [zoom, scale]).catch(() => {});
    await page.waitForTimeout(ms);
    await el.evaluate((e) => {
      e.classList.remove("demo-hl", "demo-zoom");
      e.style.transform = "";
    }).catch(() => {});
  };
  await fn(page, hl);
  texts[name] = await page.evaluate(() => document.body.innerText).catch(() => "");
  const rest = seconds * 1000 - (Date.now() - t0);
  if (rest > 0) await page.waitForTimeout(rest);
  await context.close();
  const path = await page.video().path();
  scenes.push({ name, path, seconds, url });
  console.log(name, path);
}

await scene("main", `${base}/`, 8, async (page) => { await page.mouse.move(960, 540); });
await scene("banner", `${base}/`, 6, async (p, hl) => { await hl('div[role="status"]', { ms: 5200 }); });
await scene("tile", `${base}/`, 10, async (p, hl) => { await hl('a[data-site="2011G56"]', { zoom: true, ms: 9200 }); });
await scene("map", `${base}/`, 4, async (p, hl) => { await hl("section.panel.order-3", { ms: 3400 }); });
await scene("site", `${base}/sites/2011G56`, 8, async (p, hl) => { await hl("section.panel.flex.flex-col.gap-3", { ms: 7200 }); });
await scene("why", `${base}/sites/2011G56`, 8, async (p, hl) => { await hl('section.panel:has(h2:has-text("왜 이렇게 예상했나"))', { ms: 7200 }); });
await scene("history", `${base}/sites/2011G56`, 6, async (p, hl) => {
  await hl('section.panel:has(h2:has-text("지난 녹조 발생 기록"))', { ms: 2700 });
  await hl('section.panel:has(h2:has-text("권고 조치"))', { ms: 2700 });
});
await scene("replay", `${base}/?asof=2026-07-27`, 6, async (p, hl) => {
  await hl("div[data-replay-band]", { scale: 1.7, ms: 3400 });
  await hl('a[data-site="2011G56"]', { zoom: true, ms: 2200 });
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
writeFileSync(`${outDir}/texts.json`, JSON.stringify(texts, null, 1));
console.log("done");
