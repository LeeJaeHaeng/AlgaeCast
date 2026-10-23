// 헤드라인 숫자 대조 (docs/12 §10): src/lib/numbers.ts 의 값이 reports/eval 원천 표와 같은지 빌드 전에 확인한다.
// 제출·운영 모델 = v2.1(데이터 유래 상수 누수 수정판, models/FROZEN_v2.1.md). v1·v2 는 수정 전 이력.
// 원천: tbl_leadtime.md(2020~2025, v2.1 OOF, q90≥임계·B0), tbl_holdout_2026_posthoc_v21.md(2026 v2.1·v2·v1·v1-fix·B0),
//   tbl_holdout_2025_v21.md(2025 같은 252행 v2.1·v1-fix·B0 + 수정 전 v2·v1), headline_metrics.json(전체 정밀도),
//   reports/experiments/FIX-v2.1/baseline_v2/tbl_leadtime.md(수정 전 2020~2025 감시 포착), models/FROZEN*.md, config/model.yaml(운영점).
// 지표 값은 headline_metrics.json 의 전체 정밀도 값에서 한 번만 반올림해 대조하고(이중 반올림 금지), md 표(셋째 자리)와 그 JSON 이 일치하는지도 확인한다.
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
const H = JSON.parse(read("headline_metrics.json"));
const src = readFileSync(resolve(process.cwd(), "src/lib/numbers.ts"), "utf-8");
const pick = (block, key) => num(src.match(new RegExp(`${block}:\\s*\\{[^}]*\\b${key}:\\s*(-?[\\d.]+)`))?.[1]);
const pickStr = (block, key) => src.match(new RegExp(`${block}:\\s*\\{[^}]*\\b${key}:\\s*"([^"]+)"`))?.[1];
const r2 = (v) => Math.round(v * 100) / 100;
const r3x = (v) => Math.round(v * 1000) / 1000;
const checks = [];

// ── 헤드라인(사건 포착) ───────────────────────────────────────────
const N = {
  events: { total: pick("events", "total"), detected: pick("events", "detected"), med: pick("events", "medianLeadDays"), b0: pick("events", "persistenceDetected") },
  y2026: { total: pick("y2026", "total"), detected: pick("y2026", "detected"), med: pick("y2026", "medianLeadDays"), b0: pick("y2026", "persistenceDetected") },
  prior: { total: pick("prior", "total"), detected: pick("prior", "detected"), med: pick("prior", "medianLeadDays"), b0: pick("prior", "persistenceDetected") },
};
const leadTables = (md) => {
  const t = tables(md);
  const sum = t[0];
  const det = t[2];
  return { q90: findRow(sum, "q90≥임계"), b0: findRow(sum, "B0"), leads: det.rows.filter((r) => r[0] === "q90≥임계").map((r) => num(r[col(det, "리드(E) 일")])) };
};
const LT = leadTables(read("tbl_leadtime.md"));
const LT0 = leadTables(readFileSync(resolve(root, "reports", "experiments", "FIX-v2.1", "baseline_v2", "tbl_leadtime.md"), "utf-8"));
const p26md = read("tbl_holdout_2026_posthoc_v21.md");
const p26 = tables(p26md);
const p26all = p26[0];
const p26lead = p26.find((t) => t.header.includes("방식") && t.header.includes("선행 탐지 수"));
const p26det = p26.find((t) => t.header.includes("v2.1 감시"));
const leadRow = (m, how) => p26lead.rows.find((r) => r[0] === m && r[1].startsWith(how));
const leadsOf = (h) => p26det.rows.map((r) => r[col(p26det, h)]).filter((c) => c !== "" && c !== "None").map(num);
const w21 = leadsOf("v2.1 감시");
const S = {
  prior: { total: num(LT.q90[1]), detected: num(LT.q90[2]), med: median(LT.leads), b0: num(LT.b0[2]) },
  y2026: { total: num(leadRow("v2.1", "감시")[col(p26lead, "사건 수")]), detected: num(leadRow("v2.1", "감시")[col(p26lead, "선행 탐지 수")]), med: median(w21), b0: num(leadRow("v2.1", "B0")[col(p26lead, "선행 탐지 수")]) },
};
S.events = { total: S.prior.total + S.y2026.total, detected: S.prior.detected + S.y2026.detected, med: median([...LT.leads, ...w21]), b0: S.prior.b0 + S.y2026.b0 };
if (LT.leads.length !== S.prior.detected || w21.length !== S.y2026.detected) {
  console.error(`check_numbers: 사건별 상세 행 수 불일치 (2020~25 ${LT.leads.length}/${S.prior.detected}, 2026 ${w21.length}/${S.y2026.detected})`);
  process.exit(1);
}
for (const [k, label] of [["events", "합계"], ["y2026", "2026"], ["prior", "2020~25"]]) {
  checks.push([`${label} 사건 수`, N[k].total, S[k].total]);
  checks.push([`${label} 미리 알림`, N[k].detected, S[k].detected]);
  checks.push([`${label} 중앙 리드타임(E)`, N[k].med, S[k].med]);
  checks.push([`${label} 지속성 선행 탐지`, N[k].b0, S[k].b0]);
}
checks.push(["2020~25 감시 포착 v2.1(priorWatch)", pick("priorWatch", "v21"), S.prior.detected]);
checks.push(["2020~25 감시 포착 수정 전(priorWatch)", pick("priorWatch", "before"), num(LT0.q90[2])]);
checks.push(["2020~25 사건 수(priorWatch)", pick("priorWatch", "total"), S.prior.total]);

// ── 헤드라인 지표(v2.1: 2025 같은 252행 · 2026 test 124) ───────────
const h21 = H.same252_2025.v21;
const p21 = H.posthoc2026.v21;
checks.push(["r2_log 2025", pick("r2log", "y2025"), r2(h21.r2_log)], ["r2_log 2026", pick("r2log", "y2026"), r2(p21.r2_log)]);
checks.push(["F1@10k 2025", pick("f1_10k", "y2025"), r2(h21.f1_10k)], ["F1@10k 2026", pick("f1_10k", "y2026"), r2(p21.f1_10k)]);
checks.push(["F1@10k 지속성 2025", pick("f1_10k", "persistence2025"), r2(H.same252_2025.b0.f1_10k)], ["F1@10k 지속성 2026", pick("f1_10k", "persistence2026"), r2(H.posthoc2026.b0.f1_10k)]);
checks.push(["r2_raw 2025", pick("r2raw", "y2025"), r2(h21.r2_raw)], ["r2_raw 2026", pick("r2raw", "y2026"), r2(p21.r2_raw)]);
checks.push(["nse_raw 2025", pick("nseraw", "y2025"), r2(h21.nse_raw)], ["nse_raw 2026", pick("nseraw", "y2026"), r2(p21.nse_raw)]);
checks.push(["PICP80(CQR) 2025", pick("picp80", "y2025"), r2(H.picp80_2025_same252)], ["PICP80(CQR) 2026", pick("picp80", "y2026"), r2(p21.picp80)]);

// ── 비교표(CMP) ──────────────────────────────────────────────────
const metricBlock = (b) => ({ n: pick(b, "n"), rmse: pick(b, "rmselog"), r2log: pick(b, "r2log"), r2raw: pick(b, "r2raw"), nse: pick(b, "nseraw"), f1: pick(b, "f1_10k") });
const jsonMetrics = (o) => ({ n: o.n, rmse: r2(o.rmse_log), r2log: r2(o.r2_log), r2raw: r2(o.r2_raw), nse: r2(o.nse_raw), f1: r2(o.f1_10k) });
const KMAP = { n: "n", rmse: "rmse_log", r2log: "r2_log", r2raw: "r2_raw", nse: "nse_raw", f1: "f1_10k" };
const pushMetrics = (label, ours, theirs) => {
  for (const k of Object.keys(KMAP)) checks.push([`${label} ${KMAP[k]}`, ours[k], theirs[k]]);
};
const srcEq = (t, row, o, label) => {
  for (const k of ["rmse_log", "r2_log", "r2_raw", "nse_raw", "f1_10k"]) checks.push([`원천 정합 ${label} ${k}: JSON→셋째 자리 = md 표`, 0, Math.abs(r3x(o[k]) - num(row[col(t, k)])) < 1e-9 ? 0 : 1]);
  checks.push([`원천 정합 ${label} n`, num(row[col(t, "n")]), o.n]);
};
// 2025 같은 252행
const v25 = tables(read("tbl_holdout_2025_v21.md"));
const v25h = v25.find((t) => t.header[0] === "모델" && t.header.includes("rmse_log"));
const v25cv = v25.find((t) => t.header.some((h) => h.startsWith("r2_raw 통합")));
for (const [blk, key, prefix] of [["h25v21", "v21", "v2.1"], ["h25v1fix", "v1fix", "v1-fix"], ["h25b0", "b0", "B0"]]) {
  pushMetrics(`2025 같은행 ${key}`, metricBlock(blk), jsonMetrics(H.same252_2025[key]));
  srcEq(v25h, findRow(v25h, prefix), H.same252_2025[key], `2025 ${key}`);
}
for (const [blk, key] of [["h25v2", "v2"], ["h25v1", "v1"]]) pushMetrics(`2025 같은행 ${key}(수정 전)`, metricBlock(blk), jsonMetrics(H.same252_2025[key]));
const cvCol = v25cv.header.findIndex((h) => h.startsWith("r2_raw 통합"));
for (const [m, prefix] of [["v21", "v2.1"], ["v1fix", "v1-fix"], ["b0", "B0"]]) {
  checks.push([`CV 통합 r2_raw ${m}`, pick("cvR2raw", m), r2(H.cv_pooled_r2_raw[m])]);
  checks.push([`원천 정합 CV 통합 r2_raw ${m}`, 0, Math.abs(r3x(H.cv_pooled_r2_raw[m]) - num(findRow(v25cv, prefix)[cvCol])) < 1e-9 ? 0 : 1]);
}
for (const m of ["v2", "v1"]) checks.push([`CV 통합 r2_raw ${m}(수정 전)`, pick("cvR2raw", m), r2(H.cv_pooled_r2_raw[m])]);
// 2026 사후(124조합)
for (const [blk, key, prefix] of [["p26v21", "v21", "v2.1"], ["p26v2", "v2", "v2("], ["p26v1", "v1", "v1 봉인본"], ["p26v1fix", "v1fix", "v1-fix"], ["p26b0", "b0", "B0"]]) {
  pushMetrics(`2026 ${key}`, metricBlock(blk), jsonMetrics(H.posthoc2026[key]));
  srcEq(p26all, findRow(p26all, prefix), H.posthoc2026[key], `2026 ${key}`);
}
for (const [m, k] of [["v2.1", "v21"], ["v2", "v2"], ["v1", "v1"]]) {
  checks.push([`2026 감시 선행 탐지 ${m}`, pick("p26watch", k), num(leadRow(m, "감시")[col(p26lead, "선행 탐지 수")])]);
  checks.push([`2026 감시 중앙 리드 ${m}`, pick("p26watch", `medianLeadV${k.replace("v", "").toUpperCase()}`), median(leadsOf(`${m} 감시`))]);
  checks.push([`2026 점예측 포착 ${m}`, pick("p26point", k), num(leadRow(m, "점예측")[col(p26lead, "선행 탐지 수")])]);
}
checks.push(["2026 점예측 포착 v1-fix(사건별 표)", pick("p26point", "v1fix"), leadsOf("v1-fix 점예측").length]);
checks.push(["2026 점예측 포착 v2.1(사건별 표)", pick("p26point", "v21"), leadsOf("v2.1 점예측").length]);
checks.push(["2026 사건 수(점예측)", pick("p26point", "total"), num(leadRow("v2.1", "점예측")[col(p26lead, "사건 수")])]);
checks.push(["2026 지속성 선행 탐지", pick("p26point", "persistence"), num(leadRow("v2.1", "B0")[col(p26lead, "선행 탐지 수")])]);
checks.push(["2026 감시 v2.1 = 헤드라인", 0, pick("p26watch", "v21") === N.y2026.detected && pick("p26watch", "medianLeadV21") === N.y2026.med ? 0 : 1]);

// ── 고지문: v2.1 사후 원천의 모든 표 앞에 고지, copy.ts 에 같은 문장 ────
const NOTICE = "수정본(v2.1·v1-fix)의 2026 은 블라인드가 아니다: 모델 선택·수정 규칙에 2026 을 쓰지 않았지만 팀은 v1·v2 의 2026 결과를 이미 봤다.";
{
  const lines = p26md.split(/\r?\n/);
  let seen = 0;
  let missing = 0;
  for (let i = 0; i < lines.length; i++) {
    if (!(lines[i].startsWith("|") && lines[i + 1]?.startsWith("|---"))) continue;
    seen++;
    let j = i - 1;
    while (j >= 0 && !lines[j].startsWith("#") && !lines[j].includes(NOTICE)) j--;
    if (j < 0 || !lines[j].includes(NOTICE)) missing++;
    while (lines[i + 1]?.startsWith("|")) i++;
  }
  checks.push([`2026 v2.1 원천 표 ${seen}개 중 고지문 없는 표`, 0, missing]);
  const copySrc = readFileSync(resolve(process.cwd(), "src/lib/copy.ts"), "utf-8");
  checks.push(["copy.ts 고지문 = 원천 고지문", 0, copySrc.includes(NOTICE) ? 0 : 1]);
}

// ── 동결 정보·운영점 ─────────────────────────────────────────────
{
  const f = (n) => readFileSync(resolve(root, "models", n), "utf-8");
  const fv1 = f("FROZEN.md");
  const fv2 = f("FROZEN_v2.md");
  const fv21 = f("FROZEN_v2.1.md");
  const commit = (t) => t.match(/동결 커밋: `([0-9a-f]+)`/)?.[1] ?? "";
  for (const [m, t] of [["v1meta", fv1], ["v2meta", fv2], ["v21meta", fv21]]) checks.push([`${m} 동결 커밋 ⊂ 동결 문서`, 0, commit(t).startsWith(pickStr(m, "commit") ?? "-") ? 0 : 1]);
  checks.push([`v2.1 동결 시각 ${pickStr("v21meta", "frozenKST")}`, 0, fv21.includes(`동결 시각(KST): ${pickStr("v21meta", "frozenKST")}`) ? 0 : 1]);
  checks.push([`v2 동결 시각 ${pickStr("v2meta", "frozenKST")}`, 0, fv2.includes(`동결 시각(KST): ${pickStr("v2meta", "frozenKST")}`) ? 0 : 1]);
  checks.push(["v2.1 피처 수", pick("v21meta", "features"), num(fv21.match(/피처 (\d+)개/)?.[1])]);
  checks.push(["v2.1 상류 피처 수", pick("v21meta", "upstreamFeatures"), num(fv21.match(/상류 (\d+)\(/)?.[1])]);
  checks.push(["v1 피처 수", pick("v1meta", "features"), num(fv1.match(/perc75, (\d+)개/)?.[1])]);
  const w = (k) => r3x(num(fv21.match(new RegExp(`결합 가중치[^\\n]*?${k} (-?[\\d.]+)`))?.[1]));
  for (const k of ["c1", "c3", "c2", "cg"]) checks.push([`v2.1 결합 가중치 ${k} (소수 셋째 자리)`, pick("v21weights", k), w(k)]);
  const myaml = readFileSync(resolve(root, "config", "model.yaml"), "utf-8");
  const op = num(myaml.match(/operating_point:[\s\S]*?threshold:\s*(-?[\d.]+)/)?.[1]);
  checks.push(["운영점 threshold = config/model.yaml", num(src.match(/OPERATING_POINT = \{[^}]*threshold:\s*([\d.]+)/)?.[1]), op]);
  checks.push(["운영점 비용비 = config/model.yaml", num(src.match(/OPERATING_POINT = \{[^}]*costRatio:\s*(\d+)/)?.[1]), num(myaml.match(/operating_point:[\s\S]*?cost_ratio:\s*(\d+)/)?.[1])]);
}

let bad = 0;
for (const [name, ours, theirs] of checks) {
  const ok = Math.abs(ours - theirs) < 1e-9;
  if (!ok) bad++;
  console.log(`${ok ? "OK  " : "FAIL"} ${name}: numbers.ts ${ours} / reports ${theirs}`);
}
console.log(`check_numbers: ${checks.length - bad}/${checks.length} 일치 (합계 중앙 리드타임은 ${LT.leads.length + w21.length}개 사건 리드의 중앙값)`);
process.exit(bad ? 1 : 0);
