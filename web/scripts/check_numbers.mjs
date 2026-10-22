// 헤드라인 숫자 대조 (docs/12 §10): src/lib/numbers.ts 의 값이 reports/eval 원천 표와 같은지 빌드 전에 확인한다.
// 대상: 큰 숫자 4개(미리 알림 25/28·중앙 리드, 2026 7/8·중앙 리드, 로그 R², F1@10k vs 지속성), 비교 막대(지속성 3/28), 성적표 띠.
// 원천: tbl_leadtime.md(2020~2025, q90≥임계·B0), tbl_holdout_2026_posthoc.md(2026 감시·B0), tbl_holdout_2025.md(앙상블·B0).
// v2(2026-10-22): MODELS·V2CMP 를 tbl_holdout_2025_v2.md(같은 252행)·tbl_holdout_2026_posthoc_v2.md(비블라인드 고지)·models/FROZEN*.md 와 대조.
// 지표 값(2026-10-22 정정): 셋째 자리 표 값을 다시 반올림하지 않는다(이중 반올림 금지). reports/eval/headline_metrics.json 의
//   전체 정밀도 값(v1 2025 공개 256행은 남은 가장 정밀한 넷째 자리 기록)에서 한 번만 반올림해 대조하고, md 표(셋째 자리)와 그 JSON 이 일치하는지도 확인한다.
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(process.cwd(), "..");
const evalDir = resolve(root, "reports", "eval");
if (!existsSync(evalDir)) {
  console.log("check_numbers: reports/eval 없음(배포 빌드) → 대조 생략");
  process.exit(0);
}
const read = (f) => readFileSync(resolve(evalDir, f), "utf-8");
const tables = (md) => {
  const lines = md.split(/\r?\n/);
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].startsWith("|") && lines[i + 1]?.startsWith("|---")) {
      const header = lines[i].split("|").slice(1, -1).map((c) => c.trim());
      const rows = [];
      let j = i + 2;
      while (lines[j]?.startsWith("|")) rows.push(lines[j++].split("|").slice(1, -1).map((c) => c.trim()));
      out.push({ header, rows });
      i = j;
    }
  }
  return out;
};
const num = (s) => Number(String(s).match(/-?\d+(\.\d+)?/)?.[0]);
const median = (a) => {
  const s = [...a].sort((x, y) => x - y);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};
const findRow = (t, prefix) => t.rows.find((r) => r[0].replace(/\*\*/g, "").startsWith(prefix));
const col = (t, name) => t.header.indexOf(name);
// 전체 정밀도 원천(python -m algaecast.eval.headline). 표시 값은 여기서 한 번만 반올림한다.
const H = JSON.parse(read("headline_metrics.json"));
const LP = H.limited_precision;

// numbers.ts 읽기 (TS 파일에서 숫자만 추출)
const src = readFileSync(resolve(process.cwd(), "src/lib/numbers.ts"), "utf-8");
const pick = (block, key) => num(src.match(new RegExp(`${block}:\\s*\\{[^}]*\\b${key}:\\s*(-?[\\d.]+)`))?.[1]);
const N = {
  events: { total: pick("events", "total"), detected: pick("events", "detected"), med: pick("events", "medianLeadDays"), b0: pick("events", "persistenceDetected") },
  y2026: { total: pick("y2026", "total"), detected: pick("y2026", "detected"), med: pick("y2026", "medianLeadDays"), b0: pick("y2026", "persistenceDetected") },
  prior: { total: pick("prior", "total"), detected: pick("prior", "detected"), med: pick("prior", "medianLeadDays"), b0: pick("prior", "persistenceDetected") },
  r2log: { y2025: pick("r2log", "y2025"), y2026: pick("r2log", "y2026") },
  f1: { y2025: pick("f1_10k", "y2025"), y2026: pick("f1_10k", "y2026"), b025: pick("f1_10k", "persistence2025"), b026: pick("f1_10k", "persistence2026") },
  r2raw: { y2025: pick("r2raw", "y2025"), y2026: pick("r2raw", "y2026") },
  nse: { y2025: pick("nseraw", "y2025"), y2026: pick("nseraw", "y2026") },
  picp: { y2025: pick("picp80", "y2025"), y2026: pick("picp80", "y2026") },
};

// 원천 값
const lt = tables(read("tbl_leadtime.md"));
const ltSum = lt[0]; // 경계(10k) 요약
const ltDetail = lt[2]; // 사건별 상세(10k)
const q90 = findRow(ltSum, "q90≥임계");
const b0prior = findRow(ltSum, "B0");
const priorLeads = ltDetail.rows.filter((r) => r[0] === "q90≥임계").map((r) => num(r[col(ltDetail, "리드(E) 일")]));

const ph = tables(read("tbl_holdout_2026_posthoc.md"));
const phAll = ph[0];
const phLead = ph.find((t) => t.header.includes("선행 탐지 수") && t.header.some((h) => h.includes("경보 총수(2026)")));
const phDetail = ph.find((t) => t.header.includes("첫 경보 base_date") && t.rows.some((r) => r[0].startsWith("감시")));
const watch26 = findRow(phLead, "감시");
const b026row = findRow(phLead, "B0");
const leads26 = phDetail.rows.filter((r) => r[0].startsWith("감시")).map((r) => num(r[col(phDetail, "리드(E)")]));
const ens26 = findRow(phAll, "동결 앙상블");
const b0all26 = findRow(phAll, "B0");

const h25 = tables(read("tbl_holdout_2025.md"))[0];
const ens25 = findRow(h25, "앙상블");
const b0all25 = findRow(h25, "B0");

const S = {
  prior: { total: num(q90[1]), detected: num(q90[2]), med: median(priorLeads), b0: num(b0prior[2]) },
  y2026: { total: num(watch26[1]), detected: num(watch26[2]), med: median(leads26), b0: num(b026row[2]) },
  r2log: { y2025: LP.v1_2025_public.values.r2_log, y2026: H.posthoc2026.v1.r2_log },
  f1: { y2025: LP.v1_2025_public.values.f1_10k, y2026: H.posthoc2026.v1.f1_10k, b025: LP.b0_2025_public.values.f1_10k, b026: H.posthoc2026.b0.f1_10k },
  r2raw: { y2025: LP.v1_2025_public.values.r2_raw, y2026: H.posthoc2026.v1.r2_raw },
  nse: { y2025: LP.v1_2025_public.values.nse_raw, y2026: H.posthoc2026.v1.nse_raw },
  picp: { y2025: LP.picp80_2025_public.values.picp80, y2026: H.posthoc2026.v1.picp80 },
};
S.events = { total: S.prior.total + S.y2026.total, detected: S.prior.detected + S.y2026.detected, med: median([...priorLeads, ...leads26]), b0: S.prior.b0 + S.y2026.b0 };
if (priorLeads.length !== S.prior.detected || leads26.length !== S.y2026.detected) {
  console.error(`check_numbers: 사건별 상세 행 수 불일치 (2020~25 ${priorLeads.length}/${S.prior.detected}, 2026 ${leads26.length}/${S.y2026.detected})`);
  process.exit(1);
}

const r2 = (v) => Math.round(v * 100) / 100;
const checks = [
  ["경계 사건 수(합계)", N.events.total, S.events.total],
  ["미리 알림(합계)", N.events.detected, S.events.detected],
  ["중앙 리드타임(합계, E 기준)", N.events.med, S.events.med],
  ["지속성 선행 탐지(합계)", N.events.b0, S.events.b0],
  ["2026 사건 수", N.y2026.total, S.y2026.total],
  ["2026 미리 알림", N.y2026.detected, S.y2026.detected],
  ["2026 중앙 리드타임", N.y2026.med, S.y2026.med],
  ["2026 지속성 선행 탐지", N.y2026.b0, S.y2026.b0],
  ["2020~25 사건 수", N.prior.total, S.prior.total],
  ["2020~25 미리 알림", N.prior.detected, S.prior.detected],
  ["2020~25 중앙 리드타임", N.prior.med, S.prior.med],
  ["2020~25 지속성 선행 탐지", N.prior.b0, S.prior.b0],
  ["r2_log 2025", N.r2log.y2025, r2(S.r2log.y2025)],
  ["r2_log 2026", N.r2log.y2026, r2(S.r2log.y2026)],
  ["F1@10k 2025", N.f1.y2025, r2(S.f1.y2025)],
  ["F1@10k 2026", N.f1.y2026, r2(S.f1.y2026)],
  ["F1@10k 지속성 2025", N.f1.b025, r2(S.f1.b025)],
  ["F1@10k 지속성 2026", N.f1.b026, r2(S.f1.b026)],
  ["r2_raw 2025", N.r2raw.y2025, r2(S.r2raw.y2025)],
  ["r2_raw 2026", N.r2raw.y2026, r2(S.r2raw.y2026)],
  ["nse_raw 2025", N.nse.y2025, r2(S.nse.y2025)],
  ["nse_raw 2026", N.nse.y2026, r2(S.nse.y2026)],
  ["PICP80(CQR) 2025 (v1·v2 공통)", N.picp.y2025, r2(S.picp.y2025)],
  ["PICP80(CQR) 2026 (v1·v2 공통)", N.picp.y2026, r2(S.picp.y2026)],
];
// 원천 정합: JSON 값(셋째 자리로 반올림) = 공개 md 표 값, 제한 정밀도 값은 둘째 자리 반올림이 한 가지로 정해짐
const r3x = (v) => Math.round(v * 1000) / 1000;
const mdEq = (label, jsonV, mdCell) => checks.push([`원천 정합 ${label}: JSON→셋째 자리 = md 표`, 0, Math.abs(r3x(jsonV) - num(mdCell)) < 1e-9 ? 0 : 1]);
for (const k of ["rmse_log", "r2_log", "r2_raw", "nse_raw", "f1_10k"]) {
  mdEq(`2025 v1 공개 ${k}`, LP.v1_2025_public.values[k], ens25[col(h25, k)]);
  mdEq(`2025 지속성 공개 ${k}`, LP.b0_2025_public.values[k], b0all25[col(h25, k)]);
  mdEq(`2026 v1 ${k}`, H.posthoc2026.v1[k], ens26[col(phAll, k)]);
  mdEq(`2026 지속성 ${k}`, H.posthoc2026.b0[k], b0all26[col(phAll, k)]);
}
mdEq("2025 PICP80 공개", LP.picp80_2025_public.values.picp80, ens25[col(h25, "PICP80(CQR)")]);
mdEq("2026 PICP80", H.posthoc2026.v1.picp80, ens26[col(phAll, "PICP80(CQR)")]);
for (const [name, blk] of Object.entries(LP)) {
  const amb = Object.entries(blk.unambiguous_2dp).filter(([, ok]) => !ok).map(([k]) => k);
  checks.push([`제한 정밀도 ${name}(${blk.precision}자리): 둘째 자리 결정 불가 항목 수`, 0, amb.length]);
}

// ── v2(제출·운영) vs v1(블라인드 검증) ──────────────────────────────────────────
const NOTICE = "모델 선택에 2026 미사용. 단 팀은 v1의 2026 결과를 이미 본 뒤 v2를 선택함(블라인드 아님).";
const metricBlock = (b) => ({ n: pick(b, "n"), rmse: pick(b, "rmselog"), r2log: pick(b, "r2log"), r2raw: pick(b, "r2raw"), nse: pick(b, "nseraw"), f1: pick(b, "f1_10k") });
// 비교값 = 전체 정밀도 JSON 에서 한 번 반올림. md 표(셋째 자리)는 JSON 과 같은지만 확인한다(srcMetrics 의 표 행).
const jsonMetrics = (o) => ({ n: o.n, rmse: r2(o.rmse_log), r2log: r2(o.r2_log), r2raw: r2(o.r2_raw), nse: r2(o.nse_raw), f1: r2(o.f1_10k) });
const srcMetrics = (t, row, o) => {
  for (const k of ["rmse_log", "r2_log", "r2_raw", "nse_raw", "f1_10k"]) checks.push([`원천 정합 ${row[0]} ${k}: JSON→셋째 자리 = md 표`, 0, Math.abs(r3x(o[k]) - num(row[col(t, k)])) < 1e-9 ? 0 : 1]);
  checks.push([`원천 정합 ${row[0]} n`, num(row[col(t, "n")]), o.n]);
  return jsonMetrics(o);
};
const pushMetrics = (label, ours, theirs) => {
  for (const k of ["n", "rmse", "r2log", "r2raw", "nse", "f1"]) checks.push([`${label} ${{ n: "n", rmse: "rmse_log", r2log: "r2_log", r2raw: "r2_raw", nse: "nse_raw", f1: "f1_10k" }[k]}`, ours[k], theirs[k]]);
};

// 2025 같은 252행
const v25 = tables(read("tbl_holdout_2025_v2.md"));
const v25h = v25[0];
const v25cv = v25[1];
pushMetrics("2025 같은행 v2", metricBlock("h25v2"), srcMetrics(v25h, findRow(v25h, "v2"), H.same252_2025.v2));
pushMetrics("2025 같은행 v1", metricBlock("h25v1"), srcMetrics(v25h, findRow(v25h, "v1"), H.same252_2025.v1));
pushMetrics("2025 같은행 B0", metricBlock("h25b0"), srcMetrics(v25h, findRow(v25h, "B0"), H.same252_2025.b0));
const cvCol = v25cv.header.findIndex((h) => h.startsWith("r2_raw 통합"));
for (const [m, label] of [["v2", "v2"], ["v1", "v1"], ["b0", "B0"]]) {
  checks.push([`CV 2020~24 통합 r2_raw ${label}`, pick("cvR2raw", m), r2(H.cv_pooled_r2_raw[m])]);
  checks.push([`원천 정합 CV 통합 r2_raw ${label}: JSON→셋째 자리 = md 표`, 0, Math.abs(r3x(H.cv_pooled_r2_raw[m]) - num(findRow(v25cv, label)[cvCol])) < 1e-9 ? 0 : 1]);
}

// 2026 사후(124조합) — v2 는 비블라인드
const p26md = read("tbl_holdout_2026_posthoc_v2.md");
const p26 = tables(p26md);
const p26all = p26[0];
pushMetrics("2026 v2", metricBlock("p26v2"), srcMetrics(p26all, findRow(p26all, "v2"), H.posthoc2026.v2));
pushMetrics("2026 v1", metricBlock("p26v1"), srcMetrics(p26all, findRow(p26all, "v1"), H.posthoc2026.v1));
pushMetrics("2026 B0", metricBlock("p26b0"), srcMetrics(p26all, findRow(p26all, "B0"), H.posthoc2026.b0));
const p26lead = p26.find((t) => t.header.includes("방식") && t.header.includes("선행 탐지 수"));
const leadRow = (m, how) => p26lead.rows.find((r) => r[0] === m && r[1].startsWith(how));
const p26det = p26.find((t) => t.header.includes("v2 감시 리드(E)"));
const leadsOf = (h) => p26det.rows.map((r) => r[col(p26det, h)]).filter((c) => c !== "").map(num);
const wV2 = leadsOf("v2 감시 리드(E)");
const wV1 = leadsOf("v1 감시 리드(E)");
checks.push(["2026 사건 수(v2 표)", pick("p26watch", "total"), num(leadRow("v2", "감시")[col(p26lead, "사건 수")])]);
checks.push(["2026 감시 선행 탐지 v2", pick("p26watch", "v2"), num(leadRow("v2", "감시")[col(p26lead, "선행 탐지 수")])]);
checks.push(["2026 감시 선행 탐지 v1(v2 표)", pick("p26watch", "v1"), num(leadRow("v1", "감시")[col(p26lead, "선행 탐지 수")])]);
checks.push(["2026 감시 중앙 리드 v2", pick("p26watch", "medianLeadV2"), median(wV2)]);
checks.push(["2026 감시 중앙 리드 v1(v2 표)", pick("p26watch", "medianLeadV1"), median(wV1)]);
checks.push(["2026 감시 v1·v2 사건별 리드 동일(차 0)", 0, wV1.length === wV2.length && wV1.every((v, i) => v === wV2[i]) ? 0 : 1]);
checks.push(["2026 감시 v2 = 헤드라인(7/8·21일)", 0, pick("p26watch", "v2") === N.y2026.detected && pick("p26watch", "medianLeadV2") === N.y2026.med ? 0 : 1]);
checks.push(["2026 점예측 포착 사건 수", pick("p26point", "total"), num(leadRow("v2", "점예측")[col(p26lead, "사건 수")])]);
checks.push(["2026 점예측 포착 v2", pick("p26point", "v2"), num(leadRow("v2", "점예측")[col(p26lead, "선행 탐지 수")])]);
checks.push(["2026 점예측 포착 v1", pick("p26point", "v1"), num(leadRow("v1", "점예측")[col(p26lead, "선행 탐지 수")])]);
checks.push(["2026 점예측 포착 v2(사건별 표)", pick("p26point", "v2"), leadsOf("v2 점예측 리드(E)").length]);
checks.push(["2026 지속성 선행 탐지(v2 표)", pick("p26point", "persistence"), num(leadRow("v2", "B0")[col(p26lead, "선행 탐지 수")])]);
// 2026 v2 의 모든 표 앞에 비블라인드 고지가 있는지, copy.ts 에 같은 고지문이 있는지
{
  const lines = p26md.split(/\r?\n/);
  let tablesSeen = 0;
  let missing = 0;
  for (let i = 0; i < lines.length; i++) {
    if (!(lines[i].startsWith("|") && lines[i + 1]?.startsWith("|---"))) continue;
    tablesSeen++;
    let j = i - 1;
    while (j >= 0 && !lines[j].startsWith("#") && !lines[j].includes(NOTICE)) j--;
    if (j < 0 || !lines[j].includes(NOTICE)) missing++;
    while (lines[i + 1]?.startsWith("|")) i++;
  }
  checks.push([`2026 v2 원천 표 ${tablesSeen}개 중 고지문 없는 표`, 0, missing]);
  const copySrc = readFileSync(resolve(process.cwd(), "src/lib/copy.ts"), "utf-8");
  checks.push(["copy.ts 고지문 = 원천 고지문", 0, copySrc.includes(NOTICE) ? 0 : 1]);
}

// 동결 정보 (models/FROZEN.md·FROZEN_v2.md)
{
  const pickStr = (block, key) => src.match(new RegExp(`${block}:\\s*\\{[^}]*\\b${key}:\\s*"([^"]+)"`))?.[1];
  const fv1 = readFileSync(resolve(root, "models", "FROZEN.md"), "utf-8");
  const fv2 = readFileSync(resolve(root, "models", "FROZEN_v2.md"), "utf-8");
  const c1 = fv1.match(/동결 커밋: `([0-9a-f]+)`/)?.[1] ?? "";
  const c2 = fv2.match(/동결 커밋: `([0-9a-f]+)`/)?.[1] ?? "";
  checks.push([`v1 동결 커밋 ${pickStr("v1meta", "commit")} ⊂ FROZEN.md ${c1.slice(0, 12)}`, 0, c1.startsWith(pickStr("v1meta", "commit") ?? "-") ? 0 : 1]);
  checks.push([`v2 동결 커밋 ${pickStr("v2meta", "commit")} ⊂ FROZEN_v2.md ${c2.slice(0, 12)}`, 0, c2.startsWith(pickStr("v2meta", "commit") ?? "-") ? 0 : 1]);
  checks.push([`v2 동결 시각 ${pickStr("v2meta", "frozenKST")}`, 0, fv2.includes(`동결 시각(KST): ${pickStr("v2meta", "frozenKST")}`) ? 0 : 1]);
  checks.push([`v1 봉인 시각 ${pickStr("v1meta", "sealedKST")}`, 0, p26md.includes(`v1 은 ${pickStr("v1meta", "sealedKST")} KST 봉인`) ? 0 : 1]);
  checks.push(["v2 피처 수", pick("v2meta", "features"), num(fv2.match(/피처 (\d+)개/)?.[1])]);
  checks.push(["v2 상류 피처 수", pick("v2meta", "upstreamFeatures"), num(fv2.match(/상류 (\d+)\(/)?.[1])]);
  checks.push(["v1 피처 수", pick("v1meta", "features"), num(fv1.match(/perc75, (\d+)개/)?.[1])]);
  const r3 = (v) => Math.round(v * 1000) / 1000;
  const w = (k) => r3(num(fv2.match(new RegExp(`결합 가중치[^\\n]*?${k} (-?[\\d.]+)`))?.[1]));
  for (const k of ["c1", "c3", "c2", "cg"]) checks.push([`v2 결합 가중치 ${k} (소수 셋째 자리)`, pick("v2weights", k), w(k)]);
}
let bad = 0;
for (const [name, ours, theirs] of checks) {
  const ok = Math.abs(ours - theirs) < 1e-9;
  if (!ok) bad++;
  console.log(`${ok ? "OK  " : "FAIL"} ${name}: numbers.ts ${ours} / reports ${theirs}`);
}
console.log(`check_numbers: ${checks.length - bad}/${checks.length} 일치 (합계 중앙 리드타임은 ${priorLeads.length + leads26.length}개 사건 리드의 중앙값)`);
process.exit(bad ? 1 : 0);
