// 같은 단어가 바로 이어지는 중복(예: '공식 발령 발령 없음') 검사.
//  (1) src/lib/copy.ts 의 모든 문자열과 템플릿 함수 출력(아래 CALLS 의 보기 인자로 호출; 보기 인자가 없는 함수는 '덮지 못한 함수'로 적는다)
//  (2) 실행 중인 서버의 화면 글자 — 기본 화면 12개 URL + 다시 보기 장면 3개 × (메인·지점·기록) + 전문가 보기·'그 뒤 실제로는'.
//      글자 = innerText 에 해당하는 보이는 글자(블록 요소·표 칸·SVG 글자 경계는 줄바꿈, 인라인 요소는 이어 붙임) + title·aria-label 속성(각각 한 줄).
//      --browser <playwright node_modules 경로> 를 주면 진짜 브라우저(헤드리스 Chromium)의 innerText 로 같은 검사를 한 번 더 한다.
// 토큰: 공백·문장부호(· , . ( ) — – / ~ → : ; ! ? 따옴표 괄호 등)로 나눈 뒤 **한글 음절로만 된 토큰**끼리 바로 이어서 같으면 중복.
//      줄(블록·표 칸·속성) 경계는 넘지 않는다. 숫자·영문·기호가 섞인 토큰('1만', '25℃')은 보지 않는다.
// 허용 예외(ALLOW): 뜻이 다른 같은 글자가 이어지는 경우를 {token, 이유} 로 적는다. 2026-10-27 현재 없음 — 찾으면 여기에 이유와 함께 적는다.
// 참고(실패 아님): 'XX' 꼴(같은 글자 두 번을 붙여 쓴 한 토큰, 예: 인라인 요소가 띄어쓰기 없이 붙어 '지점지점')도 따로 적는다.
// 사용: node scripts/check_dup_words.mjs                    → copy.ts 만
//      node scripts/check_dup_words.mjs http://localhost:3300 [--browser C:/.../node_modules] [--out 파일.md]
import { writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { register } from "node:module";
import { pathToFileURL } from "node:url";

// copy.ts 는 "./numbers"(확장자 없음)를 임포트하므로 Node 의 타입 제거 실행에 .ts 확장자 보정 훅을 건다
register(
  `data:text/javascript,${encodeURIComponent(`
export async function resolve(spec, ctx, next) {
  try { return await next(spec, ctx); }
  catch (e) {
    if (e?.code === "ERR_MODULE_NOT_FOUND" && /^[.][.]?[/]/.test(spec) && !/[.][cm]?[jt]sx?$/.test(spec)) return next(spec + ".ts", ctx);
    throw e;
  }
}`)}`,
  pathToFileURL("./"),
);
const copy = await import("../src/lib/copy.ts");

const args = process.argv.slice(2);
const opt = (k) => (args.indexOf(k) >= 0 ? args[args.indexOf(k) + 1] : null);
const out = opt("--out");
const browserDir = opt("--browser");
const base = args.find((a, i) => !a.startsWith("--") && !["--out", "--browser"].includes(args[i - 1])) ?? null;

/** 허용 예외: { token: "…", why: "…" } */
const ALLOW = [];

const SITES = ["2011G26", "2011G56", "2020G33", "2022G05", "3008G30"];
const SCENES = [
  ["2026-07-27", "2011G56"],
  ["2026-08-03", "2011G56"],
  ["2026-07-06", "3008G30"],
];
const URLS = [
  "/",
  ...SITES.map((s) => `/sites/${s}`),
  "/sites/2011G56?view=expert",
  "/?kiosk=1",
  "/performance",
  "/insights",
  "/about",
  "/log",
  ...SCENES.flatMap(([d, s]) => [`/?asof=${d}`, `/sites/${s}?asof=${d}`, `/log?asof=${d}`, `/?asof=${d}&view=expert`, `/sites/${s}?asof=${d}&view=expert`, `/sites/${s}?asof=${d}&after=1`]),
];

// ---------- 토큰 검사 ----------
const SEP = /[\s·,.()\[\]{}<>—–\-\/~→←↑↓:;!?"'`“”‘’「」『』|=+*%&#@^_※]+/;
const HANGUL = /^[가-힣]+$/;
/** 줄(줄바꿈·탭 경계) 안에서 바로 이어지는 같은 한글 토큰 → [{token, ctx}] */
function dupsInLine(text) {
  const hits = [];
  for (const line of String(text).split(/[\n\t]+/)) {
    const toks = line.split(SEP).filter(Boolean);
    for (let i = 1; i < toks.length; i++) {
      if (toks[i] === toks[i - 1] && HANGUL.test(toks[i]) && !ALLOW.some((a) => a.token === toks[i])) hits.push({ token: toks[i], ctx: line.trim().slice(0, 120) });
    }
  }
  return hits;
}
/** 'XX' 꼴 한 토큰(참고용): 길이 4 이상 짝수, 앞뒤 반이 같음 */
function doubledTokens(line) {
  return line
    .split(SEP)
    .filter((t) => HANGUL.test(t) && t.length >= 4 && t.length % 2 === 0 && t.slice(0, t.length / 2) === t.slice(t.length / 2))
    .map((t) => ({ token: t, ctx: line.trim().slice(0, 120) }));
}

// 양성 대조(검사기 고장 방지): 예전 조합 방식('공식 발령' + OFFICIAL_LEVEL[0].label)은 잡혀야 하고, officialLabel(0) 은 잡히지 않아야 한다
{
  const bad = copy.BOARD.log.observation("회남", "0 개/mL", `${copy.BOARD.tile.official} ${copy.OFFICIAL_LEVEL[0].label}`); // 예전 조합 → "… · 공식 발령 발령 없음"
  if (dupsInLine(bad).length !== 1 || dupsInLine(bad)[0].token !== "발령") throw new Error(`양성 대조 실패: '${bad}' 에서 '발령 발령' 을 못 잡음`);
  if (dupsInLine(copy.officialLabel(0)).length) throw new Error(`음성 대조 실패: '${copy.officialLabel(0)}'`);
  if (dupsInLine("가 나\n나 다").length) throw new Error("줄 경계를 넘어 잡음");
}

// ---------- (1) copy.ts ----------
const FMT = (v) => (v == null ? "–" : Math.round(v).toLocaleString("ko-KR"));
/** 템플릿 함수 보기 인자(경로 → 인자 묶음들). 새 템플릿을 copy.ts 에 더하면 여기도 더한다(안 더하면 '덮지 못한 함수'로 나온다) */
const CALLS = {
  kstKo: [["2026-10-23 12:08"], ["2026-10-21 09:44"]],
  n2: [[0.5], [-0.25]],
  "COMBO.enter.reco": [["강정·고령", 77]],
  "COMBO.watch.reco": [["강정·고령", 30]],
  "COMBO.persist.reco": [["칠서", 90]],
  "COMBO.improve.reco": [["물금·매리", 20]],
  "COMBO.safe.reco": [["회남", 0]],
  reasonWaterDays: [[3]],
  recommendation: [["alert", "강정·고령", 77], ["watch", "해평", 30], ["normal", "회남", 1]],
  banner: [
    [[{ combo: "enter", sites: ["강정·고령"] }, { combo: "persist", sites: ["칠서", "물금·매리"] }], "16:05"],
    [[], "16:05"],
    [[], "16:05", "2026-07-27 기준"],
  ],
  "BOARD.nextRefresh": [[5]],
  "BOARD.actionsDone": [[2, 5]],
  "BOARD.actionsMore": [[3]],
  "BOARD.log.tierChange": [["강정·고령", "안전", "◆ 대응 필요"], ["강정·고령", null, "● 안전"]],
  "BOARD.log.observation": [["강정·고령", "8,500 개/mL", "공식 발령 없음"], ["회남", "0 개/mL", "공식 발령 관심"], ["칠서", "5.4만 개/mL", "공식 발령 경계"], ["칠서", "–", "공식 발령 –"]],
  "BOARD.score.caught": [[24, 28]],
  "BOARD.score.lead": [[14]],
  "BOARD.score.year2026": [[7, 8]],
  "BOARD.score.expert": [["0.70", "0.73", "0.83", "0.84"]],
  "BOARD.failBanner": [["10.27 05:10"]],
  "BOARD.staleBanner": [[9]],
  "SITE.facility": [["대청댐"]],
  "SITE.history.caught": [[7]],
  "SITE.plain.whyOver": [["1.1만", 77]],
  "SITE.plain.whyHighChance": [["8,500", 60]],
  "SITE.plain.whyHighOnly": [["8,500", 50]],
  "SITE.plain.whyLowChance": [["55", 0]],
  "SITE.verifySummary": [[7, 10]],
  "SITE.eventSummary": [[3, 2]],
  "PERF.big.caught.sub": [[14]],
  "PERF.big.y2026.sub": [[21]],
  "PERF.big.r2log.value": [["0.78", "0.52"]],
  "PERF.big.f1.sub": [["0.70", "0.73", "0.83", "0.84"]],
  "PERF.compare.y2025": [[252]],
  "PERF.compare.y2026": [[124]],
  "PERF.compare.count": [[7, 8]],
  "PERF.compare.countLead": [[17, 20, 14]],
  "PERF.compare.prior": [[17, 20]],
  "PERF.compare.cv": [["0.20", "0.18", "0.15", "0.05"]],
  "PERF.compare.v1fix": [["0.18", "0.00", "0.80", "5", "8"]],
  "PERF.compare.weak": [["0.00", "0.70", "0.73", "0.83", "0.84"]],
  "PERF.target.rows": [[{ r25: "0.18", r26: "0.00", n25: "0.18", n26: "0.00" }]],
  "PERF.target.rowsNote": [["0.10", "0.12"]],
  "PERF.mulmoa.text": [[9]],
  "INSIGHTS.surge.body": [[12, "27.1", "3.2"]],
  targetLabel: [
    ["2026-08-10", "2026-08-03", 10662, null, FMT],
    ["2026-08-04", "2026-08-03", 10662, null, FMT],
    ["2026-08-03", "2026-08-03", 10662, null, FMT],
    ["2026-08-03", "2026-08-10", 10662, 98859, FMT],
    ["2026-08-03", "2026-08-10", 10662, 98859, FMT, { withValues: false }],
    [null, "2026-08-10", null, null, FMT],
  ],
  explainForecast: [
    [10662, 45882, 77, FMT],
    [8500, 12000, 60, FMT],
    [8500, 9000, 50, FMT],
    [55, 858, 0, FMT],
  ],
  outOfRangeTip: [["above", "641", "45,882"], ["below", "641", "45,882"]],
  LOG_MORE: [[12]],
  "REPLAY.band": [["2026-07-27"]],
  "REPLAY.bannerTail": [["2026-07-27"]],
  "REPLAY.notice": [["2026-05-04", "2026-10-22"]],
  "REPLAY.logTitle": [["2026-07-27"]],
  "REPLAY.weather.basis": [["07.21", "07.27"]],
  "REPLAY.weather.days": [[5], [1]],
  officialLabel: [[0], [1], [2], [3], [null], [9]],
  levelOfCells: [[0]],
  comboOf: [[0, "normal"]],
  outOfRange: [[1, 0, 2]],
};
const strings = []; // {path, text}
const uncovered = [];
const unknownFns = [];
function walk(v, path) {
  if (typeof v === "string") strings.push({ path, text: v });
  else if (Array.isArray(v)) v.forEach((x, i) => walk(x, `${path}[${i}]`));
  else if (typeof v === "function") {
    const calls = CALLS[path];
    if (!calls) {
      uncovered.push(path);
      return;
    }
    for (const a of calls) {
      let r;
      try {
        r = v(...a);
      } catch (e) {
        unknownFns.push(`${path}(${JSON.stringify(a)}) → 오류 ${e.message}`);
        continue;
      }
      if (typeof r === "string") strings.push({ path: `${path}(${JSON.stringify(a).slice(0, 40)})`, text: r });
      else if (r && typeof r === "object") walk(r, `${path}(${JSON.stringify(a).slice(0, 40)})`);
    }
  } else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) walk(x, path ? `${path}.${k}` : k);
}
for (const [k, v] of Object.entries(copy)) walk(v, k);
const copyHits = [];
const copyDoubled = [];
for (const s of strings) {
  for (const h of dupsInLine(s.text)) copyHits.push({ where: s.path, ...h });
  for (const h of doubledTokens(s.text)) copyDoubled.push({ where: s.path, ...h });
}

const lines = [`# 같은 단어 중복 검사 — ${new Date().toISOString().slice(0, 16)}`, "", `허용 예외 ${ALLOW.length}개${ALLOW.length ? `: ${ALLOW.map((a) => `'${a.token}'(${a.why})`).join(", ")}` : ""}`, ""];
lines.push("## (1) copy.ts", "", `문자열·템플릿 출력 ${strings.length}개 검사 → 중복 **${copyHits.length}건**`);
for (const h of copyHits) lines.push(`- ${h.where}: '${h.token} ${h.token}' … ${h.ctx}`);
if (copyDoubled.length) lines.push(`참고 'XX' 꼴 토큰 ${copyDoubled.length}건: ${copyDoubled.map((h) => `${h.where} '${h.token}'`).join(", ")}`);
if (uncovered.length) lines.push(`덮지 못한 함수(보기 인자 없음) ${uncovered.length}개: ${uncovered.join(", ")}`);
if (unknownFns.length) lines.push(`호출 오류 ${unknownFns.length}개: ${unknownFns.join("; ")}`);
lines.push("");

// ---------- (2) 화면 ----------
const BLOCK = /^(div|p|li|ul|ol|tr|td|th|table|thead|tbody|tfoot|section|header|footer|main|nav|h[1-6]|br|hr|article|aside|form|button|dl|dt|dd|blockquote|pre|figure|figcaption|label|option|select|summary|details|text|tspan|title|desc|caption|legend|fieldset|svg|a|time)$/i;
const decode = (s) => s.replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&");
/** innerText 근사: 블록·표 칸·SVG 글자 경계 = 줄바꿈, 인라인 = 이어 붙임. 속성(title·aria-label)은 따로 한 줄씩 */
function textLines(html) {
  const noScript = html.replace(/<script[\s\S]*?<\/script>/gi, "\n").replace(/<style[\s\S]*?<\/style>/gi, "\n").replace(/<!--[\s\S]*?-->/g, "");
  const attrs = [...noScript.matchAll(/\s(?:title|aria-label)="([^"]*)"/g)].map((m) => decode(m[1]));
  const body = noScript.replace(/<\/?([a-zA-Z][\w-]*)\b[^>]*>/g, (m, tag) => (BLOCK.test(tag) ? "\n" : ""));
  return [...decode(body).split(/\n+/), ...attrs].map((l) => l.replace(/\s+/g, " ").trim()).filter(Boolean);
}
let pageHits = 0;
let pageDoubled = [];
if (base) {
  lines.push(`## (2) 화면 글자(${base}) — HTML 기준`, "", "| URL | 줄 수 | 중복 | 내용 |", "|---|---|---|---|");
  for (const u of URLS) {
    const r = await fetch(base + u);
    const html = await r.text();
    const ls = textLines(html);
    const hits = ls.flatMap((l) => dupsInLine(l));
    pageDoubled.push(...ls.flatMap((l) => doubledTokens(l)).map((h) => ({ where: u, ...h })));
    pageHits += hits.length;
    lines.push(`| ${u} | ${ls.length} | ${hits.length ? `**${hits.length}**` : 0} | ${hits.map((h) => `'${h.token} ${h.token}' … ${h.ctx}`).join("<br>").replace(/\|/g, "/")} |`);
  }
  lines.push("");
  if (browserDir) {
    // 진짜 브라우저 innerText(헤드리스) — 블록 경계·숨김 요소를 브라우저 규칙대로
    const require = createRequire(pathToFileURL(browserDir.replace(/\/?$/, "/")));
    const { chromium } = require("playwright");
    const b = await chromium.launch({ headless: true });
    try {
      const ctx = await b.newContext({ viewport: { width: 1350, height: 940 } });
      const p = await ctx.newPage();
      lines.push(`## (2′) 화면 글자 — 브라우저 innerText 기준(1350×940)`, "", "| URL | 줄 수 | 중복 | 내용 |", "|---|---|---|---|");
      for (const u of URLS) {
        await p.goto(base + u, { waitUntil: "networkidle" });
        await p.waitForTimeout(800);
        const ls = await p.evaluate(() => {
          const t = document.body.innerText.split(/[\n\t]+/);
          const at = [...document.querySelectorAll("[title],[aria-label]")].flatMap((el) => [el.getAttribute("title"), el.getAttribute("aria-label")]).filter(Boolean);
          return [...t, ...at].map((l) => l.replace(/\s+/g, " ").trim()).filter(Boolean);
        });
        const hits = ls.flatMap((l) => dupsInLine(l));
        pageDoubled.push(...ls.flatMap((l) => doubledTokens(l)).map((h) => ({ where: `${u} (브라우저)`, ...h })));
        pageHits += hits.length;
        lines.push(`| ${u} | ${ls.length} | ${hits.length ? `**${hits.length}**` : 0} | ${hits.map((h) => `'${h.token} ${h.token}' … ${h.ctx}`).join("<br>").replace(/\|/g, "/")} |`);
      }
      lines.push("");
    } finally {
      await b.close();
    }
  }
  const seenD = new Map();
  for (const h of pageDoubled) if (!seenD.has(h.token)) seenD.set(h.token, h);
  if (seenD.size) lines.push(`참고 'XX' 꼴 토큰(화면) ${seenD.size}종: ${[...seenD.values()].map((h) => `'${h.token}'(${h.where})`).join(", ")}`, "");
}
const total = copyHits.length + pageHits;
lines.push(`합계: copy.ts ${copyHits.length}건 + 화면 ${pageHits}건 = **${total}건**${uncovered.length ? ` (덮지 못한 함수 ${uncovered.length}개 — 보기 인자를 CALLS 에 더할 것)` : ""}`);
const text = lines.join("\n");
console.log(text);
if (out) writeFileSync(out, text + "\n", "utf-8");
process.exit(total || uncovered.length ? 1 : 0);
