// 과거 시점 다시 보기 누수 검사: 실행 중인 서버에서 장면 3개 × 9쪽(메인·상황 기록·지점 상세 5곳·전문가 보기 2) × '그 뒤 실제로는' 끔/켬 을 열어
// HTML(첫 화면 + __next_f RSC 스크립트)과 RSC 페이로드(RSC: 1 요청)에 그날(asof) 이후 관측의 날짜·값이 없는지 본다.
// 사용: node scripts/check_asof.mjs [http://localhost:3300] [--out 파일.md]   (Node 22.18+/24 — src/lib/replay.ts 를 타입 제거로 바로 읽음)
// 정답 자료는 Supabase(anon 키, 읽기 전용)에서 읽는다: web/.env.local 의 NEXT_PUBLIC_SUPABASE_URL·ANON_KEY (키 값은 출력하지 않음).
// 예측 run 은 앱과 같은 규칙: 고정한 다시 보기 run(REPLAY_RUN_ID)이 있으면 그것, 없으면 최신 성공 run.
//
// 기준 날짜 limit = asof(토글 끔) 또는 asof+21(토글 켬). '허용 날짜' = 그 지점의 그날 예측 목표일 하나(예측 대상 날짜, 관측 아님).
//   토글 켬이어도 그 뒤 21일은 그림(메인 지점 모니터 SVG 좌표, 지점 상세 큰 차트의 actual 점)으로만 나와야 하므로
//   HTML 의 보이는 글자·속성·ISO 날짜와 메인·상황 기록의 RSC 는 언제나 asof 까지, 그 뒤 21일 값도 메인·기록은 쪽 전체·지점 상세는 보이는 글자에서 막는다.
//   지점 상세 = '앞으로 7일' 구역(data-replay-forecast)만 그 지점 목표일, 그 밖 글자는 없음(RSC 는 목표일 — 차트 예상 점),
//   메인 = 지점 블록(/sites/ID 로 가는 타일·모니터)마다 그 지점 목표일·블록 밖은 없음(RSC 는 지점 목표일들), 상황 기록 = 없음.
//   보이는 글자에서는 그 목표일도 '예상' 표시 바로 앞(예: '08.10 예상(7일 뒤)')에서만 허용하고, HTML 의 ISO 날짜(속성 등)로는 허용하지 않는다.
//   지점 상세 '지난 녹조 발생 기록'(data-replay-history) 구역은 허용 목록 없이 모든 날짜 ≤ asof(토글과 무관) — HTML 글자·속성, RSC 의 그 구역 하위 트리,
//   HTML 안 RSC 스크립트(__next_f 를 풀어서)의 그 구역 모두. 표 행 집합(첫 초과일·공식 발령일)과 요약 건수는 DB(공식 발령일 ≤ asof)와 같아야 한다(⑨).
// 검사
//  ① 값: limit 뒤 관측값(1천 이상, 1,900~2,100 은 연도와 헷갈려 제외, 원값·천 단위 쉼표)이 없다 — 지점 상세는 그 지점, 메인·기록은 전 지점.
//     같은 값이 허용된 관측에도 있으면 '애매'로 따로 센다.
//  ② 날짜: limit 뒤 날짜가 허용 날짜 밖에서 나오지 않는다 — 형식 4가지: YYYY-MM-DD(HTML 전체·RSC), YYYY.MM.DD(사건 표, 글자·RSC),
//     MM.DD(글자), 'M월 D일'(글자·RSC). 글자 = 보이는 글자 + title·aria-label 속성.
//  ③ 예측: asof 뒤 기준일 예측의 값(예상값·범위·가능성의 원래 실수)이 없다. 양성 대조: 장면 지점 상세에 그날 예측 예상값(원래 실수)이 있다.
//  ④ 띠 문구("다시 보기 — asof 기준.")가 있고 장면 이름(메뉴 제목)이 띠에 없다  ⑤ 사건 성적 문장("경계 사건 n건 중 m건을 미리 알림"·"2026년 경계 사건 n건 중")이 없다
//     (정규식 양성 대조: 기본 화면 / 에서는 이 문장이 잡혀야 한다)
//  ⑥ 구조(RSC): 브라우저로 넘어가는 자료 객체마다 obs_date·date(측정)·base_date·event_date 등이 limit/asof 이하, obs_cell_count 가 있으면 target_date ≤ asof,
//     actual(그 뒤 실측)은 토글 켬일 때만 asof < date ≤ asof+21 — 값의 크기와 관계없이 날짜로 막는다(1천 미만·1,900~2,100 값의 빈틈).
//  ⑦ SVG(메인 지점 모니터): 측정 선·점(stroke=var(--line-obs))의 x 가 모두 그날 위치 이하, 분홍 점선(var(--after))은 토글 켬일 때만 (그날, 그날+21] 안.
//  ⑧ 값으로 못 보는 limit 뒤 관측(1천 미만·1,900~2,100·애매)은 그 날짜가 어떤 형식으로도 나오지 않는지(허용 목표일과 같은 날이면 ⑥·⑦이 막음)를 센다.
//  ⑨ 대조: 지점 상세 = 사건 구역(위), 상황 기록(/log) = 예상 단계 변화 줄이 다시 보기 run 예측으로 만든 것(tierChangesAsOf, 시각·지점)과 같고
//     새 측정 줄 수가 DB 관측(그날까지 30일)과 같다 — v_event_log(최신 run) 에 기대지 않는지.
//  ⑩ 날씨(실측, 메인): '그날까지 7일 날씨(실측)' 칸(data-replay-weather=asof)의 출처 줄 창이 (그날−6)~그날(창 끝 = 그날)이고,
//     지점별 7일 평균 기온·비 합계·자료 일수가 DB weather_daily(그날−6 ≤ 관측일 ≤ 그날)를 같은 함수(summarizeWeatherAsOf)로 집계한 값과 같다.
// 그 밖: 장면 3개가 허용 범위(max(2026-01-01, run 첫 기준일) ~ 마지막 기준일) 안, 기본 화면에는 띠 없음, 범위 밖·형식 틀림은 안내만.
import { readFileSync, writeFileSync } from "node:fs";
import { createClient } from "@supabase/supabase-js";
import { REPLAY_MIN, REPLAY_RUN_ID, SCENES, addDaysISO, summarizeWeatherAsOf, tierChangesAsOf, weatherWindow } from "../src/lib/replay.ts";

const args = process.argv.slice(2);
const outIdx = args.indexOf("--out");
const out = outIdx >= 0 ? args[outIdx + 1] : null;
const base = args.find((a, i) => !a.startsWith("--") && (outIdx < 0 || i !== outIdx + 1)) ?? "http://localhost:3300";
const SITES = ["2011G26", "2011G56", "2020G33", "2022G05", "3008G30"];

const env = Object.fromEntries(
  readFileSync(".env.local", "utf8")
    .split(/\r?\n/)
    .filter((l) => l.includes("=") && !l.trimStart().startsWith("#"))
    .map((l) => [l.slice(0, l.indexOf("=")).trim(), l.slice(l.indexOf("=") + 1).trim().replace(/^"|"$/g, "")]),
);
const sb = createClient(env.NEXT_PUBLIC_SUPABASE_URL, env.NEXT_PUBLIC_SUPABASE_ANON_KEY, { auth: { persistSession: false } });

// ---------- 정답 자료(DB, 읽기만) ----------
const fixed = (await sb.from("model_runs").select("run_id").eq("run_id", REPLAY_RUN_ID).eq("status", "success").limit(1)).data?.[0]?.run_id;
const latest = (await sb.from("model_runs").select("run_id").eq("status", "success").order("run_at", { ascending: false }).limit(1)).data?.[0]?.run_id;
const runId = fixed ?? latest;
if (!runId) throw new Error("다시 보기 run 을 찾지 못함");
const all = async (q) => {
  const rows = [];
  for (let from = 0; ; from += 1000) {
    const { data, error } = await q().range(from, from + 999);
    if (error) throw error;
    rows.push(...data);
    if (data.length < 1000) break;
  }
  return rows;
};
const OBS = await all(() => sb.from("observations").select("site_id,obs_date,cell_count").gte("obs_date", "2025-01-01").order("obs_date"));
const PRED = await all(() => sb.from("predictions").select("site_id,base_date,target_date,pred_cell_count,q50,q10_cqr,q90_cqr,p_alert,tier").eq("run_id", runId).gte("base_date", REPLAY_MIN).order("base_date"));
const EVENTS = await all(() => sb.from("bloom_events").select("event_id,site_id,first_exceed_date,official_alert_date,detected_watch").order("first_exceed_date"));
const SITE_ROWS = (await sb.from("sites").select("site_id,name")).data ?? [];
// 단계 변화 비교 시작점(앱 getReplayTierSeed 와 같은 규칙): 지점별 2026 직전 1년 안 마지막 예상 단계
const SEED = [];
for (const r of (await sb.from("predictions").select("site_id,base_date,target_date,tier").eq("run_id", runId).lt("base_date", REPLAY_MIN).gte("base_date", addDaysISO(REPLAY_MIN, -366)).order("base_date", { ascending: false }).order("target_date", { ascending: false })).data ?? [])
  if (!SEED.some((x) => x.site_id === r.site_id)) SEED.push({ site_id: r.site_id, tier: r.tier });
const lastBase = (await sb.from("predictions").select("base_date").eq("run_id", runId).order("base_date", { ascending: false }).limit(1)).data?.[0]?.base_date ?? null;
const firstBase = PRED[0]?.base_date ?? null;
const lo = firstBase && firstBase > REPLAY_MIN ? firstBase : REPLAY_MIN;

// ---------- 도구 ----------
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const numRe = (v) => new RegExp(`(?<![\\d.])${esc(String(v))}(?!\\d)(?!\\.\\d)`, "g");
const commaRe = (v) => new RegExp(`(?<![\\d,])${esc(Math.round(v).toLocaleString("en-US"))}(?![\\d])(?!,\\d)`, "g");
const ctx = (s, i) => s.slice(Math.max(0, i - 50), i + 60).replace(/\s+/g, " ");
const decode = (s) => s.replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
function visibleText(html) {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&[a-z#0-9]+;/gi, " ")
    .replace(/\s+/g, " ");
}
/** 보이는 글자 + title·aria-label 속성(툴팁·읽어 주기 글자) */
function textOf(html) {
  const noScript = html.replace(/<script[\s\S]*?<\/script>/gi, " ").replace(/<style[\s\S]*?<\/style>/gi, " ");
  const attrs = [...noScript.matchAll(/\s(?:title|aria-label)="([^"]*)"/g)].map((m) => decode(m[1]));
  return `${visibleText(noScript)} ${attrs.join(" ")}`;
}
const pad = (n) => String(n).padStart(2, "0");
/** 글자에서 날짜 찾기: kinds = iso·dot·mmdd·ko 중 고름. year = 연도 없는 형식(MM.DD·M월 D일)의 해 */
function datesIn(s, kinds, year) {
  const found = [];
  if (kinds.includes("iso")) for (const m of s.matchAll(/(?<!\d)(20\d\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))(?!\d)/g)) found.push({ d: m[1], i: m.index, f: "YYYY-MM-DD" });
  if (kinds.includes("dot")) for (const m of s.matchAll(/(?<![\d.])(20\d\d)\.(0[1-9]|1[0-2])\.(0[1-9]|[12]\d|3[01])(?![\d])/g)) found.push({ d: `${m[1]}-${m[2]}-${m[3]}`, i: m.index, f: "YYYY.MM.DD" });
  if (kinds.includes("mmdd")) for (const m of s.matchAll(/(?<![\d.])(0[1-9]|1[0-2])\.(0[1-9]|[12]\d|3[01])(?![\d.])/g)) found.push({ d: `${year}-${m[1]}-${m[2]}`, i: m.index, f: "MM.DD" });
  if (kinds.includes("ko"))
    for (const m of s.matchAll(/(?:(20\d\d)년\s?)?(?<!\d)(1[0-2]|[1-9])월\s?([12]\d|3[01]|[1-9])일(\s?(?:오전|오후)\s?\d{1,2}시(?:\s?\d{1,2}분)?)?/g)) {
      // 모델 고정·봉인 시각(예: '2026년 10월 23일 오후 12시 8분 … 고정') 은 관측이 아닌 모델 메타데이터 — 시각까지 붙고 바로 뒤에 고정/봉인이 오는 것만 뺀다
      const meta = !!m[4] && /^[^.。]{0,24}(고정|봉인)/.test(s.slice(m.index + m[0].length));
      found.push({ d: `${m[1] ?? year}-${pad(m[2])}-${pad(m[3])}`, i: m.index, f: "M월 D일", meta });
    }
  return found;
}
/** 지점의 그날 예측(기준일 ≤ asof 중 최신, 같은 기준일이면 목표일 늦은 것) — 앱(pickPredAsOf)과 같은 규칙 */
const pick = (sid, asof) => PRED.filter((r) => r.site_id === sid && r.base_date <= asof).sort((a, b) => b.base_date.localeCompare(a.base_date) || b.target_date.localeCompare(a.target_date))[0] ?? null;
async function get(url, rsc) {
  const r = await fetch(url, rsc ? { headers: { RSC: "1" } } : {});
  return { status: r.status, type: r.headers.get("content-type") ?? "", body: await r.text() };
}
/** 메인 HTML 을 지점 블록(/sites/ID 로 가는 <a>)과 나머지로 나눈다 */
function splitBlocks(html) {
  const blocks = [];
  const rest = html.replace(/<a\b([^>]*\bhref="\/sites\/(\w+)[^"]*"[^>]*)>([\s\S]*?)<\/a>/g, (m, attrs, sid) => {
    blocks.push({ sid, html: m });
    return " ";
  });
  return { blocks, rest };
}
/** RSC 페이로드의 평평한 객체({...} 안에 {} 없음) 중 JSON 으로 읽히는 것 */
function flatObjects(s) {
  const outObjs = [];
  for (const m of s.matchAll(/\{[^{}]*\}/g)) {
    try {
      const o = JSON.parse(m[0]);
      if (o && typeof o === "object" && !Array.isArray(o)) outObjs.push(o);
    } catch {}
  }
  return outObjs;
}
/** MiniChart 와 같은 가로 좌표(%) */
function miniX(sid, asof, after) {
  const p = pick(sid, asof);
  const to = addDaysISO(asof, 21);
  const end = after ? new Date(p?.target_date && p.target_date > to ? p.target_date : to) : p?.target_date ? new Date(p.target_date) : new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 60 - 7);
  return (d) => ((new Date(d).getTime() - start.getTime()) / (end.getTime() - start.getTime())) * 100;
}
const svgXs = (d) => [...d.matchAll(/[ML]\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)/g)].map((m) => Number(m[1]));
/** HTML 안 RSC 스크립트(self.__next_f.push([1,"..."]))를 풀어 RSC 글 하나로 잇는다 */
function nextF(html) {
  let s = "";
  for (const m of html.matchAll(/self\.__next_f\.push\((\[[\s\S]*?\])\)<\/script>/g)) {
    try {
      const a = JSON.parse(m[1]);
      if (a[0] === 1 && typeof a[1] === "string") s += a[1];
    } catch {}
  }
  return s;
}
/** RSC 글에서 marker 를 품은 ["$","section",…] 하위 트리 범위들(문자열 안 괄호는 건너뜀) */
function sectionRanges(s, marker) {
  const out = [];
  for (let from = 0; ; ) {
    const i = s.indexOf(marker, from);
    if (i < 0) break;
    const st = s.lastIndexOf('["$","section"', i);
    let depth = 0;
    let inStr = false;
    let esc = false;
    let end = -1;
    for (let k = st; st >= 0 && k < s.length; k++) {
      const c = s[k];
      if (inStr) {
        if (esc) esc = false;
        else if (c === "\\") esc = true;
        else if (c === '"') inStr = false;
        continue;
      }
      if (c === '"') inStr = true;
      else if (c === "[" || c === "{") depth++;
      else if (c === "]" || c === "}") {
        depth--;
        if (depth === 0) {
          end = k + 1;
          break;
        }
      }
    }
    if (st < 0 || end < 0) {
      out.push(null); // 찾았는데 트리를 못 읽음 → 실패로 센다
      break;
    }
    out.push([st, end]);
    from = end;
  }
  return out;
}
/** HTML 에서 data-<attr>="asof" 인 <section> 하나(안에 section 없음)와 나머지 */
function cutSection(html, attr, asof) {
  const re = new RegExp(`<section [^>]*data-${attr}="${asof}"[^>]*>[^]*?</section>`); // 역슬래시 없이: [^] = 아무 글자
  const m = html.match(re);
  return m ? { sec: m[0], rest: html.slice(0, m.index) + " " + html.slice(m.index + m[0].length) } : { sec: null, rest: html };
}
const SCORE_RE = /경계 사건 \d+건 중 \d+건을 미리 알림|2026년 경계 사건 \d+건 중/;

const lines = [`# 다시 보기 누수 검사(강화판) — ${new Date().toISOString().slice(0, 16)}`, "", `기준: ${base}, 다시 보기 run ${runId.slice(0, 8)}…(${fixed ? "고정 run" : `**고정 run 없음 → 최신 run 대체**`}), 관측 ${OBS.length}행·예측 ${PRED.length}행(2026), 허용 범위 ${lo} ~ ${lastBase}`, ""];
let fails = 0;

// ---------- 장면 3개가 허용 범위 안 ----------
lines.push("## 장면 3개 허용 범위", "", "| 장면 | asof | 지점 | 범위 안 | 그날 예측(기준일→목표일) |", "|---|---|---|---|---|");
for (const s of SCENES) {
  const inRange = !!lastBase && s.asof >= lo && s.asof <= lastBase;
  const p = pick(s.siteId, s.asof);
  if (!inRange || !p) fails++;
  lines.push(`| ${s.id} | ${s.asof} | ${s.siteId} | ${inRange ? "예" : "**아니오**"} | ${p ? `${p.base_date}→${p.target_date}` : "**없음**"} |`);
}
lines.push("");

// ---------- 정규식 양성 대조(기본 화면에서는 성적 문장이 있어야) ----------
{
  const h = await get(base + "/", false);
  const ok = SCORE_RE.test(visibleText(h.body));
  if (!ok) fails++;
  lines.push(`성적 문장 정규식 양성 대조(기본 화면 /): ${ok ? "잡힘(정상)" : "**안 잡힘 — 정규식 고장**"}`, "");
}

lines.push(
  "## 장면 × 쪽 × 토글",
  "",
  "| URL | 응답 | 막는 관측값(애매) | ① 값 | ② 날짜 | ③ 예측 값 | ④⑤ 띠·성적 | ⑥ 구조(객체) | ⑦ SVG(지점 모니터) | ⑧ 값 대신 날짜로 막은 관측 | ⑨ 사건 구역·기록 대조 | ⑩ 날씨(실측) | 양성 대조 |",
  "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
);
let pages = 0;
const mmdd = (d) => `${d.slice(5, 7)}.${d.slice(8, 10)}`;
for (const scene of SCENES) {
  const asof = scene.asof;
  const yr = asof.slice(0, 4);
  // ⑩ 정답: DB weather_daily 그날−6 ≤ 관측일 ≤ 그날 → 앱과 같은 함수로 집계
  const wWin = weatherWindow(asof);
  const WX = (await sb.from("weather_daily").select("site_id,obs_date,ta_mean,rn_sum").gte("obs_date", wWin.from).lte("obs_date", wWin.to)).data ?? [];
  const WANT_W = summarizeWeatherAsOf(WX, SITES, asof);
  for (const after of [false, true]) {
    const limit = after ? addDaysISO(asof, 21) : asof; // 이 날짜 뒤 관측은 보이면 안 됨
    const target = Object.fromEntries(SITES.map((s) => [s, pick(s, asof)?.target_date ?? null]));
    const big = (o) => o.cell_count != null && o.cell_count >= 1000 && !(o.cell_count >= 1900 && o.cell_count <= 2100);
    const forbidPred = PRED.filter((p) => p.base_date > asof).flatMap((p) => [p.pred_cell_count, p.q50, p.q10_cqr, p.q90_cqr, p.p_alert]).filter((v) => v != null && !Number.isInteger(v));
    const paths = ["/", "/log", ...SITES.map((s) => `/sites/${s}`), `/?view=expert`, `/sites/${scene.siteId}?view=expert`];
    for (const p of paths) {
      const [path, extra] = p.split("?");
      const kind = path === "/" ? "main" : path === "/log" ? "log" : "site";
      const scope = kind === "site" ? [path.slice(7)] : SITES;
      const okVals = new Set(OBS.filter((o) => scope.includes(o.site_id) && o.obs_date <= limit).map((o) => o.cell_count));
      const later = OBS.filter((o) => scope.includes(o.site_id) && o.obs_date > limit && o.cell_count != null);
      const forbidObs = later.filter((o) => big(o) && !okVals.has(o.cell_count));
      const ambiguous = later.filter((o) => big(o)).length - forbidObs.length;
      const byDateOnly = later.filter((o) => !big(o) || okVals.has(o.cell_count)); // ⑧
      const qs = new URLSearchParams(extra ?? "");
      qs.set("asof", asof);
      if (after) qs.set("after", "1");
      const url = `${path}?${qs.toString()}`;
      const html = await get(base + url, false);
      const rsc = await get(base + url, true);
      pages++;
      const bodies = [html.body, rsc.body];
      // ① 값
      const hitsV = [];
      for (const o of forbidObs)
        for (const b of bodies)
          for (const re of [numRe(o.cell_count), commaRe(o.cell_count)]) {
            const m = re.exec(b);
            if (m) hitsV.push(`${o.site_id} ${o.obs_date} ${o.cell_count} … ${ctx(b, m.index)}`);
          }
      // 토글 켬: 그 뒤 21일(asof < 날짜 ≤ asof+21) 값은 그림(메인 SVG 좌표·지점 상세 actual 점)으로만 — 메인·기록은 쪽 전체, 지점 상세는 보이는 글자에 숫자로 나오면 안 됨
      if (after) {
        const okAsof = new Set(OBS.filter((o) => scope.includes(o.site_id) && o.obs_date <= asof).map((o) => o.cell_count));
        const afterVals = OBS.filter((o) => scope.includes(o.site_id) && o.obs_date > asof && o.obs_date <= limit && big(o) && !okAsof.has(o.cell_count));
        const where = kind === "site" ? [textOf(html.body.replace(/<script[^]*?<\/script>/gi, " "))] : bodies;
        for (const o of afterVals)
          for (const b of where)
            for (const re of [numRe(o.cell_count), commaRe(o.cell_count)]) {
              const m = re.exec(b);
              if (m) hitsV.push(`(그 뒤 21일 값) ${o.site_id} ${o.obs_date} ${o.cell_count} … ${ctx(b, m.index)}`);
            }
      }
      // ② 날짜(허용 = 그 지점 목표일 하나)
      const hitsD = new Set();
      const allowedSite = kind === "site" ? new Set([target[scope[0]]].filter(Boolean)) : new Set();
      const allowedUnion = kind === "main" ? new Set(Object.values(target).filter(Boolean)) : allowedSite;
      const none = new Set();
      const metaSeen = new Set();
      // lim: 이 구역에서 보여도 되는 마지막 날(기본 limit, 사건 구역은 asof).
      // label = true(보이는 글자): 허용 목표일도 '예상' 표시 바로 앞(예: '08.10 예상(7일 뒤)')에서만 허용 — 같은 날짜가 측정일 등으로 새면 잡는다
      const LABEL_RE = /^(?:[\d.-]+|(?:\d{4}년\s?)?\d{1,2}월\s?\d{1,2}일)\s*예상/;
      const scan = (s, kinds, allowed, where, lim = limit, label = false) => {
        for (const f of datesIn(s, kinds, yr)) {
          if (f.meta) {
            metaSeen.add(f.d);
            continue;
          }
          if (f.d <= lim) continue;
          const ok = allowed.has(f.d) && (!label || LABEL_RE.test(s.slice(f.i, f.i + 24)));
          if (!ok) hitsD.add(`${where} ${f.f} ${f.d}${allowed.has(f.d) ? "('예상' 표시 밖)" : ""} … ${ctx(s, f.i)}`);
        }
      };
      const hitsH = []; // ⑨ 사건 구역·기록 대조
      let cmp9 = "–";
      const htmlText = html.body.replace(/<script[\s\S]*?<\/script>/gi, " ");
      if (kind === "main") {
        const { blocks, rest } = splitBlocks(htmlText);
        for (const b of blocks) {
          const allow = new Set([target[b.sid]].filter(Boolean));
          scan(b.html, ["iso"], none, `HTML[${b.sid}]`, asof); // HTML 의 ISO 날짜(속성 등)에는 목표일도 없어야 함
          scan(textOf(b.html), ["dot", "mmdd", "ko"], allow, `글자[${b.sid}]`, asof, true);
        }
        scan(rest, ["iso"], none, "HTML[블록 밖]", asof);
        scan(textOf(rest), ["dot", "mmdd", "ko"], none, "글자[블록 밖]", asof);
      } else if (kind === "site") {
        // 지점 상세: 사건 구역 = 허용 없이 asof 까지, 예상 구역 = 그 지점 목표일 허용, 그 밖 = 허용 없음
        const h = cutSection(htmlText, "replay-history", asof);
        const f = cutSection(h.rest, "replay-forecast", asof);
        if (!h.sec) hitsH.push("사건 구역(data-replay-history) 없음");
        if (!f.sec) hitsH.push("예상 구역(data-replay-forecast) 없음");
        if (h.sec) {
          scan(h.sec, ["iso"], none, "HTML[사건 구역]", asof);
          scan(textOf(h.sec), ["dot", "mmdd", "ko"], none, "글자[사건 구역]", asof);
        }
        if (f.sec) {
          scan(f.sec, ["iso"], none, "HTML[예상 구역]", asof);
          scan(textOf(f.sec), ["dot", "mmdd", "ko"], allowedSite, "글자[예상 구역]", asof, true);
        }
        scan(f.rest, ["iso"], none, "HTML[그 밖]", asof);
        scan(textOf(f.rest), ["dot", "mmdd", "ko"], none, "글자[그 밖]", asof);
        // 사건 표 행 집합·요약 건수 = DB(이 지점, 공식 발령일 ≤ asof)
        const want = EVENTS.filter((e) => e.site_id === scope[0] && e.official_alert_date <= asof);
        const wantSet = want.map((e) => `${e.first_exceed_date}|${e.official_alert_date}`).sort();
        const tbl = (h.sec ?? "").match(/<table[^]*?<\/table>/g)?.find((t) => t.includes("처음 1만을 넘은 날")) ?? "";
        const got = [...tbl.matchAll(/<tr[^>]*>([^]*?)<\/tr>/g)]
          .map((m) => [...m[1].matchAll(/<td[^>]*>([^]*?)<\/td>/g)].map((c) => visibleText(c[1]).match(/20\d\d\.\d\d\.\d\d/)?.[0]?.replace(/\./g, "-") ?? null))
          .filter((cells) => cells.length >= 2)
          .map((cells) => `${cells[0]}|${cells[1]}`)
          .sort();
        const sm = visibleText(h.sec ?? "").match(/경계 사건 (\d+)건 중 (\d+)건/);
        const sumOk = want.length ? !!sm && Number(sm[1]) === want.length && Number(sm[2]) === want.filter((e) => e.detected_watch).length : !sm && (h.sec ?? "").includes("기록된 경계 사건이 없습니다");
        if (JSON.stringify(got) !== JSON.stringify(wantSet)) hitsH.push(`사건 표 행 ${got.length}개 ≠ DB ${wantSet.length}개 (화면 ${got.filter((g) => !wantSet.includes(g)).join(",") || "-"} / DB 만 ${wantSet.filter((g) => !got.includes(g)).join(",") || "-"})`);
        if (!sumOk) hitsH.push(`사건 요약 건수 다름(화면 ${sm ? `${sm[1]}/${sm[2]}` : "없음"}, DB ${want.length}/${want.filter((e) => e.detected_watch).length})`);
        cmp9 = `사건 ${got.length}행=DB ${wantSet.length}`;
      } else {
        scan(htmlText, ["iso"], none, "HTML", asof);
        scan(textOf(htmlText), ["dot", "mmdd", "ko"], none, "글자", asof);
      }
      // HTML 안의 RSC 스크립트(__next_f)와 RSC 페이로드: 연도 있는 형식 + 'M월 D일'
      const scripts = [...html.body.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/gi)].map((m) => m[1]).join("\n");
      // 스크립트·RSC: 지점 상세만 토글 켬일 때 그 뒤 21일 날짜를 허용(큰 차트의 actual 점 — ⑥ 이 actual 에만 있는지 본다), 메인·기록은 언제나 asof 까지
      const rscLim = kind === "site" ? limit : asof;
      scan(scripts, ["iso", "dot", "ko"], allowedUnion, "HTML 스크립트", rscLim);
      if (kind === "site") {
        // RSC 와 HTML 안 RSC(__next_f 를 풀어서): 사건 구역 하위 트리는 허용 없이 asof 까지(4형식), 나머지는 목표일 허용
        for (const [where, s] of [["RSC", rsc.body], ["HTML 스크립트(풀어서)", nextF(html.body)]]) {
          const rs = sectionRanges(s, `"data-replay-history":"${asof}"`);
          if (!rs.length || rs.includes(null)) hitsH.push(`${where}: 사건 구역 트리 없음/못 읽음`);
          let rest = s;
          for (const r of rs.filter(Boolean).reverse()) {
            scan(s.slice(r[0], r[1]), ["iso", "dot", "mmdd", "ko"], none, `${where}[사건 구역]`, asof);
            rest = rest.slice(0, r[0]) + " " + rest.slice(r[1]);
          }
          scan(rest, ["iso", "dot", "ko"], allowedUnion, where, rscLim);
        }
      } else scan(rsc.body, ["iso", "dot", "ko"], allowedUnion, "RSC", rscLim);
      if (kind === "log") {
        // ⑨ 상황 기록 = 새 측정(DB 관측, 그날까지 30일) + 예상 단계 변화(다시 보기 run 예측으로 만든 것)
        const items = [...html.body.matchAll(/<li[^>]*>\s*<time[^>]*datetime="([^"]+)"[^>]*>[^]*?<\/time>([^]*?)<\/li>/gi)].map((m) => ({ t: m[1], text: visibleText(m[2]).trim() }));
        const tierGot = items.filter((i) => i.text.includes(" 예상 단계 ")).map((i) => `${i.t}|${i.text.slice(0, i.text.indexOf(" 예상 단계 "))}`).sort();
        const tierWant = tierChangesAsOf(PRED, SEED, SITE_ROWS, asof).map((e) => `${e.event_time}|${e.site_name}`).sort();
        const obsGot = items.filter((i) => i.text.includes(" 새 측정 ")).length;
        const lo30 = addDaysISO(asof, -30);
        const obsWant = OBS.filter((o) => o.obs_date >= lo30 && o.obs_date <= asof).length;
        if (JSON.stringify(tierGot) !== JSON.stringify(tierWant)) hitsH.push(`단계 변화 ${tierGot.length}줄 ≠ 다시 보기 run ${tierWant.length}줄`);
        if (obsGot !== obsWant) hitsH.push(`새 측정 ${obsGot}줄 ≠ DB ${obsWant}줄`);
        if (items.length !== tierGot.length + obsGot) hitsH.push(`그 밖의 줄 ${items.length - tierGot.length - obsGot}개(run 기록 등)`);
        cmp9 = `단계 ${tierGot.length}=run ${tierWant.length}·측정 ${obsGot}=DB ${obsWant}`;
      }
      // ③ 예측 값
      const hitsP = [];
      for (const v of forbidPred) for (const b of bodies) if (numRe(v).test(b)) hitsP.push(String(v));
      // ④⑤ 띠·성적 문장
      const vt = visibleText(html.body);
      const bandM = html.body.match(/<div[^>]*data-replay-band="[^"]*"[^>]*>([\s\S]*?)<\/div>\s*<\/div>/);
      const bandText = bandM ? visibleText(bandM[1]) : "";
      const sceneNameInBand = /장면|경계 진입|미리 알리지 못한|첫 초과/.test(bandText); // 장면 이름(결과를 알려 주는 말)은 메뉴에만
      const band = html.body.includes(`다시 보기 — ${asof} 기준.`) && !!bandM && !sceneNameInBand;
      const score = !SCORE_RE.test(vt);
      // ⑥ 구조(RSC 객체)
      const hitsS = [];
      for (const o of flatObjects(rsc.body)) {
        const chk = (k, max) => {
          if (typeof o[k] === "string" && /^\d{4}-\d\d-\d\d/.test(o[k]) && o[k].slice(0, 10) > max) hitsS.push(`${k}=${o[k]} ${JSON.stringify(o).slice(0, 90)}`);
        };
        chk("obs_date", limit);
        for (const k of ["latest_obs_date", "base_date", "event_date", "first_exceed_date", "official_alert_date", "first_watch_date", "first_alert_date"]) chk(k, asof);
        if (o.obs_cell_count != null && typeof o.target_date === "string" && o.target_date > asof) hitsS.push(`실측 있는 목표일 ${o.target_date} > asof`);
        if (typeof o.date === "string") {
          if (o.obs != null && o.date > asof) hitsS.push(`측정 점 ${o.date} > asof`);
          if (o.past_pred != null && o.date > asof) hitsS.push(`지난 예상 점 ${o.date} > asof`);
          if (o.actual != null && (!after || o.date <= asof || o.date > limit)) hitsS.push(`그 뒤 실측 점 ${o.date} (토글 ${after ? "켬" : "끔"})`);
          if ((o.pred != null || o.lo != null || o.hi != null) && o.date > asof && !allowedUnion.has(o.date)) hitsS.push(`예상 점 ${o.date} 허용 목표일 아님`);
          // 그날 뒤 날짜 점에 실려도 되는 값은 예상(pred·lo·hi, 목표일)과 '그 뒤 실측'(actual, 토글 켬)뿐 — 물 온도·물 흐름·날씨 등 다른 값이 있으면 누수
          if (o.date > asof) {
            const other = Object.keys(o).filter((k) => !["date", "obs", "past_pred", "pred", "lo", "hi", "actual"].includes(k) && o[k] != null);
            if (other.length) hitsS.push(`그날 뒤 점 ${o.date} 에 ${other.join("·")}`);
            if (!["obs", "past_pred", "pred", "lo", "hi", "actual"].some((k) => o[k] != null)) hitsS.push(`그날 뒤 빈 점 ${o.date}`);
          }
        }
      }
      // ⑦ SVG(메인 지점 모니터)
      let svg = "–";
      const hitsG = [];
      if (kind === "main") {
        let nObs = 0;
        let nAfter = 0;
        for (const b of splitBlocks(html.body).blocks) {
          const sm = b.html.match(/<svg[^>]*viewBox="0 0 100 100"[^>]*>([\s\S]*?)<\/svg>/);
          if (!sm) continue;
          const xp = miniX(b.sid, asof, after);
          const xa = xp(asof);
          const xe = xp(addDaysISO(asof, 21));
          for (const pm of sm[1].matchAll(/<path\b([^>]*)\/?>/g)) {
            const d = pm[1].match(/\sd="([^"]*)"/)?.[1] ?? "";
            const stroke = pm[1].match(/\sstroke="([^"]*)"/)?.[1] ?? "";
            const xs = svgXs(d);
            if (stroke === "var(--line-obs)") {
              nObs += xs.length;
              for (const x of xs) if (x > xa + 0.011) hitsG.push(`${b.sid} 측정 x=${x} > 그날 ${xa.toFixed(2)}`);
            } else if (stroke === "var(--after)") {
              nAfter += xs.length;
              if (!after) hitsG.push(`${b.sid} 토글 끔인데 분홍 점선`);
              for (const x of xs) if (x <= xa - 0.011 || x > xe + 0.011) hitsG.push(`${b.sid} 분홍 x=${x} 범위(${xa.toFixed(2)}, ${xe.toFixed(2)}] 밖`);
            }
          }
        }
        const expAfter = after ? OBS.filter((o) => o.obs_date > asof && o.obs_date <= limit && o.cell_count != null).length : 0;
        // 분홍 점: 점선(1개 path에 n점) + 점(n개 path) → 2n
        const afterOk = !after || nAfter === expAfter * 2;
        if (!afterOk) hitsG.push(`분홍 점 ${nAfter}개 ≠ 기대 ${expAfter * 2}`);
        if (nObs === 0) hitsG.push("측정 점이 하나도 없음(검사 무력)");
        svg = hitsG.length ? `**${hitsG.length}**` : `0 (측정 ${nObs}점${after ? `·분홍 ${nAfter}` : ""})`;
      }
      // ⑩ 날씨(실측) 칸 — 메인만: 창 끝 = 그날, 값·자료 일수 = DB 집계
      const hitsW = [];
      let cmpW = "–";
      if (kind === "main") {
        const wsec = html.body.match(/<section\b[^>]*data-weather-panel[^>]*>[^]*?<\/section>/)?.[0] ?? "";
        if (!wsec) hitsW.push("날씨 칸(data-weather-panel) 없음");
        else {
          const attr = wsec.match(/data-replay-weather="([^"]*)"/)?.[1];
          if (attr !== asof) hitsW.push(`다시 보기 날씨 칸 아님(data-replay-weather=${attr ?? "없음"} — 예보 칸?)`);
          const wt = visibleText(wsec);
          if (!wt.includes("그날까지 7일 날씨(실측)")) hitsW.push("제목이 '그날까지 7일 날씨(실측)' 아님");
          if (/예보/.test(wt)) hitsW.push("날씨 칸에 '예보' 글자");
          const bm = wt.match(/(\d\d\.\d\d)~(\d\d\.\d\d)/);
          if (!bm) hitsW.push("출처 줄의 날짜 창(MM.DD~MM.DD) 없음");
          else {
            if (bm[2] !== mmdd(asof)) hitsW.push(`창 끝 ${bm[2]} ≠ 그날 ${mmdd(asof)}`);
            if (bm[1] !== mmdd(wWin.from)) hitsW.push(`창 시작 ${bm[1]} ≠ 그날−6 ${mmdd(wWin.from)}`);
          }
          const rowsGot = [...(wsec.match(/<tbody[^>]*>([^]*?)<\/tbody>/)?.[1] ?? "").matchAll(/<tr[^>]*>([^]*?)<\/tr>/g)].map((m) => [...m[1].matchAll(/<td[^>]*>([^]*?)<\/td>/g)].map((c) => visibleText(c[1]).trim()));
          let nRows = 0;
          for (const cells of rowsGot) {
            const name = (cells[0] ?? "").replace(/\s*\([^()]*\)$/, "").trim();
            const sid = SITE_ROWS.find((s) => s.name === name)?.site_id;
            const want = WANT_W.find((w) => w.site_id === sid);
            if (!sid || !want) {
              hitsW.push(`지점 이름 모름: ${cells[0]}`);
              continue;
            }
            nRows++;
            const wantTa = want.ta_mean != null ? `${want.ta_mean.toFixed(1)}℃` : "–";
            const wantRn = want.rn_sum != null ? `${want.rn_sum.toFixed(1)}mm` : "–";
            if (cells[1] !== wantTa) hitsW.push(`${name} 기온 ${cells[1]} ≠ DB ${wantTa}`);
            if (cells[2] !== wantRn) hitsW.push(`${name} 비 ${cells[2]} ≠ DB ${wantRn}`);
            const note = cells[0].match(/\(([^()]*)\)$/)?.[1] ?? null;
            const wantNote = want.days >= 7 ? null : want.days ? `${want.days}일 자료` : "관측 자료 없음";
            if (note !== wantNote) hitsW.push(`${name} 자료 일수 표시 '${note ?? "없음"}' ≠ '${wantNote ?? "없음"}'`);
          }
          if (nRows !== SITES.length) hitsW.push(`날씨 행 ${nRows}개 ≠ 지점 ${SITES.length}개`);
          cmpW = hitsW.length ? `**${hitsW.length}**` : `${nRows}행=DB(${mmdd(wWin.from)}~${mmdd(asof)})`;
        }
      }
      // ⑧ 값으로 못 보는 관측 → 그 날짜가 어디에도 없는지(허용 목표일과 같은 날은 ⑥·⑦ 담당)
      const allDates = new Set([...datesIn(html.body, ["iso"], yr), ...datesIn(textOf(htmlText), ["dot", "mmdd", "ko"], yr), ...datesIn(rsc.body, ["iso", "dot", "ko"], yr)].filter((f) => !f.meta).map((f) => f.d));
      let byDateHit = 0;
      let byDateTarget = 0;
      for (const o of byDateOnly) {
        if (o.obs_date === target[o.site_id]) byDateTarget++;
        else if (allDates.has(o.obs_date)) byDateHit++;
      }
      // 양성 대조: 장면 지점 상세 = 그날 예측 예상값(원래 실수)이 실려 있다(고정 run 을 쓰는지), 토글 켬 = 21일 안 관측값이 실려 있다
      let pos = "–";
      if (kind === "site" && path === `/sites/${scene.siteId}`) {
        const pp = pick(scene.siteId, asof);
        const predOk = pp && numRe(pp.pred_cell_count).test(rsc.body);
        let s = `예측 ${predOk ? "있음" : "**없음**"}`;
        if (!predOk) fails++;
        if (after) {
          const mine = OBS.filter((o) => o.site_id === scene.siteId && o.obs_date > asof && o.obs_date <= limit && o.cell_count != null && o.cell_count >= 1000);
          const seen = mine.filter((o) => numRe(o.cell_count).test(rsc.body) || numRe(o.cell_count).test(html.body));
          s += ` · 21일 값 ${seen.length}/${mine.length}`;
          if (!mine.length || seen.length !== mine.length) fails++;
        }
        pos = s;
      }
      const ok = html.status === 200 && rsc.status === 200 && rsc.type.includes("text/x-component") && !hitsV.length && !hitsD.size && !hitsP.length && band && score && !hitsS.length && !hitsG.length && !byDateHit && !hitsH.length && !hitsW.length;
      if (!ok) fails++;
      const n = (a) => (a ? `**${a}**` : 0);
      lines.push(
        `| ${url} | ${html.status}/${rsc.status}${rsc.type.includes("text/x-component") ? "" : " (RSC 아님)"} | ${forbidObs.length}(${ambiguous}) | ${n(hitsV.length)} | ${n(hitsD.size)}${metaSeen.size ? ` (모델 고정 시각 ${[...metaSeen].sort().join("·")} 제외)` : ""} | ${n(hitsP.length)} | ${band ? "띠 있음" : "**띠 없음/장면 이름**"}·${score ? "성적 없음" : "**성적 있음**"} | ${n(hitsS.length)} | ${svg} | ${byDateOnly.length}건 중 발견 ${n(byDateHit)}(목표일과 같은 날 ${byDateTarget}) | ${hitsH.length ? `**${hitsH.length}**` : cmp9} | ${cmpW} | ${pos} |`,
      );
      for (const h of [...hitsV.slice(0, 3), ...[...hitsD].slice(0, 4), ...hitsP.slice(0, 3), ...hitsS.slice(0, 3), ...hitsG.slice(0, 3), ...hitsH.slice(0, 4), ...hitsW.slice(0, 4)]) lines.push(`|  ↳ ${h.replace(/\|/g, "/")} | | | | | | | | | | | | |`);
    }
  }
}
// 기본 화면(파라미터 없음)에는 띠가 없어야 한다
lines.push("", "## 기본 화면·범위 밖", "", "| URL | 응답 | 결과 |", "|---|---|---|");
for (const p of ["/", "/sites/2011G56", "/log"]) {
  const h = await get(base + p, false);
  const band = h.body.includes("다시 보기 — ");
  if (band || h.status !== 200) fails++;
  lines.push(`| ${p} (기본 화면) | ${h.status} | ${band ? "**띠 있음(잘못)**" : "띠 없음(정상)"} |`);
}
// 범위 밖·형식 틀림: 오류 없이 현재 화면 + 안내(실제 범위가 문구에 들어 있는지)
for (const p of ["/?asof=2025-08-01", "/?asof=2026-05-03", "/?asof=2026-13-40", "/?asof=abc", "/sites/2011G56?asof=2099-01-01", "/log?asof=2026-02-30"]) {
  const h = await get(base + p, false);
  const band = h.body.includes("다시 보기 — ");
  const note = h.body.includes("data-replay-notice");
  const rangeOk = visibleText(h.body).includes(`다시 보기는 ${lo}부터 ${lastBase}까지`);
  if (h.status !== 200 || band || !note || !rangeOk) fails++;
  lines.push(`| ${p} (범위 밖·형식 틀림) | ${h.status} | ${band ? "**띠 있음(잘못)**" : "띠 없음"} · ${note ? "안내 있음" : "**안내 없음**"} · ${rangeOk ? `범위 ${lo}~${lastBase} 문구` : "**범위 문구 틀림**"} |`);
}
lines.push("", `페이지 ${pages}개 × (HTML + RSC), 실패 ${fails}건`);
const text = lines.join("\n");
console.log(text);
if (out) writeFileSync(out, text + "\n", "utf-8");
process.exit(fails ? 1 : 0);
