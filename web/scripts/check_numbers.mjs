// 헤드라인 숫자 대조 (docs/12 §10): src/lib/numbers.ts 의 값이 reports/eval 원천 표와 같은지 빌드 전에 확인한다.
// 대상: 큰 숫자 4개(미리 알림 25/28·중앙 리드, 2026 7/8·중앙 리드, 로그 R², F1@10k vs 지속성), 비교 막대(지속성 3/28), 성적표 띠.
// 원천: tbl_leadtime.md(2020~2025, q90≥임계·B0), tbl_holdout_2026_posthoc.md(2026 감시·B0), tbl_holdout_2025.md(앙상블·B0).
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
  r2log: { y2025: num(ens25[col(h25, "r2_log")]), y2026: num(ens26[col(phAll, "r2_log")]) },
  f1: { y2025: num(ens25[col(h25, "f1_10k")]), y2026: num(ens26[col(phAll, "f1_10k")]), b025: num(b0all25[col(h25, "f1_10k")]), b026: num(b0all26[col(phAll, "f1_10k")]) },
  r2raw: { y2025: num(ens25[col(h25, "r2_raw")]), y2026: num(ens26[col(phAll, "r2_raw")]) },
  nse: { y2025: num(ens25[col(h25, "nse_raw")]), y2026: num(ens26[col(phAll, "nse_raw")]) },
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
];
let bad = 0;
for (const [name, ours, theirs] of checks) {
  const ok = Math.abs(ours - theirs) < 1e-9;
  if (!ok) bad++;
  console.log(`${ok ? "OK  " : "FAIL"} ${name}: numbers.ts ${ours} / reports ${theirs}`);
}
console.log(`check_numbers: ${checks.length - bad}/${checks.length} 일치 (합계 중앙 리드타임은 ${priorLeads.length + leads26.length}개 사건 리드의 중앙값)`);
process.exit(bad ? 1 : 0);
