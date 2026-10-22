// 배포 후 숫자 검사: src/lib/numbers.ts 의 헤드라인·v1·v2 값이 운영 화면(보이는 글자)에 그대로 나오는지 확인한다.
// 빌드 전 check_numbers.mjs 가 numbers.ts ↔ reports/eval 원천을 대조하고, 이 스크립트는 numbers.ts ↔ 배포 화면을 대조한다.
// 사용: node scripts/check_deployed_numbers.mjs https://algaecast-7.vercel.app  → 0 이면 전부 일치
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const base = process.argv[2] ?? "http://localhost:3300";
const src = readFileSync(resolve(process.cwd(), "src/lib/numbers.ts"), "utf-8");
const block = (name) => src.match(new RegExp(`${name}:\\s*\\{([^}]*)\\}`))?.[1] ?? "";
const val = (name, key) => Number(block(name).match(new RegExp(`\\b${key}:\\s*(-?[\\d.]+)`))?.[1]);
const visible = (html) =>
  html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");
const f2 = (v) => [v.toFixed(2), v.toFixed(2).replace("-", "−")];

const pages = {};
for (const p of ["/", "/performance", "/about"]) {
  const r = await fetch(base + p);
  pages[p] = visible(await r.text());
}
const all = Object.values(pages).join(" ");
const checks = [
  // 블라인드 서사(v1)·리드타임(v1·v2 공통)
  ["/", `${val("events", "total")}건 중 ${val("events", "detected")}건`],
  ["/", `${val("y2026", "total")}건 중 ${val("y2026", "detected")}건`],
  ["/performance", `${val("events", "total")}건 중 ${val("events", "detected")}건`],
  ["/performance", `${val("y2026", "total")}건 중 ${val("y2026", "detected")}건`],
  ["/performance", `중앙값 ${val("events", "medianLeadDays")}일`],
  ["/performance", `중앙 ${val("y2026", "medianLeadDays")}일`],
  // v1 점예측 지표(성능 큰 숫자)
  ["/performance", `${val("r2log", "y2025").toFixed(2)} / ${val("r2log", "y2026").toFixed(2)}`],
  ["/performance", `${val("f1_10k", "y2025").toFixed(2)} / ${val("f1_10k", "y2026").toFixed(2)}`],
  // v2 줄
  ["/performance", `${val("h25v2", "r2log").toFixed(2)} / ${val("p26v2", "r2log").toFixed(2)}`],
  ["/performance", `${val("h25v2", "f1_10k").toFixed(2)} / ${val("p26v2", "f1_10k").toFixed(2)}`],
  ["/performance", `${val("p26point", "total")}건 중 ${val("p26point", "v2")}건`],
  ["/performance", `${val("p26point", "total")}건 중 ${val("p26point", "v1")}건`],
  // 고지문·동결 커밋
  ["/performance", "모델 선택에 2026 미사용. 단 팀은 v1의 2026 결과를 이미 본 뒤 v2를 선택함(블라인드 아님)"],
  ["/performance", "9dca86c"],
  ["/about", "9dca86c"],
  ["/about", "13ac483"],
];
// v1·v2 비교표의 모든 값(2자리)이 성능 페이지에 있는지
for (const b of ["h25v2", "h25v1", "h25b0", "p26v2", "p26v1", "p26b0"]) {
  for (const k of ["rmselog", "r2log", "r2raw", "nseraw", "f1_10k"]) checks.push(["/performance", f2(val(b, k))]);
}
for (const k of ["v2", "v1"]) checks.push(["/performance", f2(val("cvR2raw", k))]);

let bad = 0;
for (const [p, want] of checks) {
  const opts = Array.isArray(want) ? want : [want];
  const ok = opts.some((w) => pages[p].includes(w));
  if (!ok) bad++;
  console.log(`${ok ? "OK  " : "FAIL"} ${p} ${opts[0]}`);
}
console.log(`check_deployed_numbers: ${checks.length - bad}/${checks.length} 일치 (${base}, 화면 글자 ${all.length.toLocaleString()}자)`);
process.exit(bad ? 1 : 0);
