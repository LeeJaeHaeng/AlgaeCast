// 배포 후 숫자 검사: src/lib/numbers.ts 의 헤드라인(v2.1)·비교표 값이 운영 화면(보이는 글자)에 그대로 나오는지 확인한다.
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
  // 헤드라인(v2.1)
  ["/", `${val("events", "total")}건 중 ${val("events", "detected")}건`],
  ["/", `${val("y2026", "total")}건 중 ${val("y2026", "detected")}건`],
  ["/performance", `${val("events", "total")}건 중 ${val("events", "detected")}건`],
  ["/performance", `${val("y2026", "total")}건 중 ${val("y2026", "detected")}건`],
  ["/performance", `중앙값 ${val("events", "medianLeadDays")}일`],
  ["/performance", `중앙값 ${val("y2026", "medianLeadDays")}일`],
  ["/performance", `${val("r2log", "y2025").toFixed(2)} / ${val("r2log", "y2026").toFixed(2)}`],
  ["/performance", `${val("f1_10k", "y2025").toFixed(2)} / ${val("f1_10k", "y2026").toFixed(2)}`],
  // 2026 점예측 포착(v2.1·v2·v1·v1-fix)
  ["/performance", `${val("p26point", "total")}건 중 ${val("p26point", "v21")}건`],
  ["/performance", `${val("p26point", "total")}건 중 ${val("p26point", "v1")}건`],
  // 2020~2025 감시 포착 v2.1·수정 전
  ["/performance", `v2.1 ${val("priorWatch", "v21")}건(수정 전 ${val("priorWatch", "before")}건)`],
  // 고지문·누수 안내·동결 커밋
  ["/performance", "수정본(v2.1·v1-fix)의 2026 은 블라인드가 아니다"],
  ["/performance", "2026년 자료까지 포함한 전 기간으로 계산돼 있었음을 발견"],
  ["/performance", "217260e"],
  ["/about", "217260e"],
  ["/about", "9dca86c"],
  ["/about", "13ac483"],
];
// 비교표의 모든 값(2자리)이 성능 페이지에 있는지
for (const b of ["h25v21", "h25v2", "h25v1", "h25b0", "p26v21", "p26v2", "p26v1", "p26b0"]) {
  for (const k of ["rmselog", "r2log", "r2raw", "nseraw", "f1_10k"]) checks.push(["/performance", f2(val(b, k))]);
}
for (const k of ["v21", "v2", "v1", "b0"]) checks.push(["/performance", f2(val("cvR2raw", k))]);
for (const k of ["r2raw", "f1_10k"]) checks.push(["/performance", f2(val("p26v1fix", k))]);

let bad = 0;
for (const [p, want] of checks) {
  const opts = Array.isArray(want) ? want : [want];
  const ok = opts.some((w) => pages[p].includes(w));
  if (!ok) bad++;
  console.log(`${ok ? "OK  " : "FAIL"} ${p} ${opts[0]}`);
}
console.log(`check_deployed_numbers: ${checks.length - bad}/${checks.length} 일치 (${base}, 화면 글자 ${all.length.toLocaleString()}자)`);
process.exit(bad ? 1 : 0);
