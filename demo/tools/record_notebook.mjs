// 1부: JupyterLab 에서 제출 패키지 노트북을 셀 순서대로 실행하며 녹화. 셀별 시작/종료 시각(영상 기준 초)을 cells.json 에 기록.
// 사용: node record_notebook.mjs <jupyter_url_with_token> <out_dir>
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const [url, outDir] = process.argv.slice(2);
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, recordVideo: { dir: outDir, size: { width: 1920, height: 1080 } } });
const t0 = Date.now();
const now = () => (Date.now() - t0) / 1000;
const page = await context.newPage();
await page.goto(url, { waitUntil: "networkidle" });
await page.waitForSelector("#jp-main-dock-panel", { timeout: 120000 });
// 노트북 열기
await page.goto(url.replace(/\/lab.*$/, "/lab/tree/notebooks/01_train_eval.ipynb") + (url.includes("token=") ? "?token=" + url.split("token=")[1] : ""), { waitUntil: "networkidle" });
await page.waitForSelector(".jp-Notebook .jp-Cell", { timeout: 120000 });
await page.waitForTimeout(2500);
// 커널 선택 대화상자가 뜨면 기본값으로 선택
const dlg = page.locator(".jp-Dialog button.jp-mod-accept");
if (await dlg.count()) await dlg.first().click();
// 뉴스 알림 닫기, 왼쪽 사이드바 접기(파일 탐색기 탭 클릭)
const no = page.locator("button:has-text('No')");
if (await no.count()) await no.first().click().catch(() => {});
await page.locator("#jp-main-content-panel").first().click({ position: { x: 900, y: 300 } }).catch(() => {});
await page.keyboard.press("Control+b");
await page.waitForTimeout(800);
if (await page.locator("#jp-left-stack").isVisible().catch(() => false)) await page.locator(".jp-SideBar.jp-mod-left li[title='File Browser']").first().click().catch(() => {});
await page.screenshot({ path: `${outDir}/dbg_open.png` });
// 왼쪽 사이드바 접기, 글자 키우기
await page.keyboard.press("Control+b");
await page.addStyleTag({ content: ".jp-Notebook { font-size: 17px !important; } .jp-Cell .CodeMirror, .jp-Cell .cm-editor { font-size: 15px !important; } .jp-OutputArea-output pre { font-size: 14px !important; }" });
await page.waitForTimeout(1000);
// 커널 준비 대기
await page.waitForFunction(() => !/Busy|Starting|Connecting/i.test(document.querySelector(".jp-Notebook-ExecutionIndicator, .jp-KernelName, #jp-main-statusbar")?.textContent ?? ""), null, { timeout: 120000 }).catch(() => {});
await page.waitForTimeout(1500);

const cells = page.locator(".jp-Notebook .jp-Cell");
const n = await cells.count();
const log = [];
for (let i = 0; i < n; i++) {
  const cell = cells.nth(i);
  const noBtn = page.locator("button:has-text('No')");
  if (await noBtn.count()) await noBtn.first().click().catch(() => {});
  await cell.scrollIntoViewIfNeeded();
  const isCode = (await cell.getAttribute("class"))?.includes("jp-CodeCell");
  const editor = cell.locator(".jp-Editor, .jp-RenderedMarkdown, .jp-InputArea-editor").first();
  await editor.click({ position: { x: 200, y: 8 } }).catch(() => cell.click());
  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
  const start = now();
  await page.keyboard.press("Shift+Enter");
  if (isCode) {
    // 실행 완료: 프롬프트가 [*] 가 아니고 숫자
    // 실행 중([*])이 되었다가 숫자로 바뀔 때까지; 10초마다 디버그 캡처
    let seenBusy = false;
    for (let k = 0; k < 180; k++) {
      const p = await cell.locator(".jp-InputPrompt").first().textContent().catch(() => "");
      if (/\*/.test(p)) seenBusy = true;
      if (/\[\s*\d+\s*\]/.test(p) && (seenBusy || k > 2)) break;
      if (k % 10 === 0) await page.screenshot({ path: `${outDir}/dbg_${i}_${k}.png` });
      await page.waitForTimeout(1000);
    }
    // 출력이 보이도록 잠시 정지
    await cell.scrollIntoViewIfNeeded();
    await page.waitForTimeout(2500);
  } else {
    await page.waitForTimeout(600);
  }
  const end = now();
  const prompt = isCode ? await cell.locator(".jp-InputPrompt").first().textContent() : "md";
  const outText = isCode ? (await cell.locator(".jp-OutputArea").first().textContent().catch(() => "")).slice(0, 160) : "";
  log.push({ i, isCode, start, end, prompt, outText });
  console.log(JSON.stringify(log.at(-1)));
}
await page.waitForTimeout(2000);
const tEnd = now();
await context.close();
const video = await page.video();
const path = await video.path();
writeFileSync(`${outDir}/cells.json`, JSON.stringify({ video: path, tEnd, cells: log }, null, 1));
await browser.close();
console.log("done", path, tEnd);
