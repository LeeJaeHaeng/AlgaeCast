// reports/eval·eda 의 표(md)·그림(png), contingency_T24 사후 표, models/FROZEN_T24.md(제출·운영)·FROZEN_v2.1.md·FROZEN.md·FROZEN_v2.md(이력) 를 web 로 동기화: md 는 src/generated/reports.json(빌드 시 임포트), png 는 public/reports
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd(), "..");
const srcDirs = [path.join(root, "reports", "eval"), path.join(root, "reports", "eda")];
// Vercel 빌드처럼 상위 저장소가 없으면(web/ 만 업로드) 커밋된 src/generated/reports.json 을 그대로 쓴다
if (!srcDirs.some((d) => fs.existsSync(d))) {
  console.log("reports/ 없음 — 커밋된 src/generated/reports.json 유지");
  process.exit(0);
}
const pubDir = path.join(process.cwd(), "public", "reports");
fs.mkdirSync(pubDir, { recursive: true });
const md = {};
for (const d of srcDirs) {
  if (!fs.existsSync(d)) continue;
  for (const f of fs.readdirSync(d)) {
    const p = path.join(d, f);
    if (f.endsWith(".md") && f.startsWith("tbl_")) md[f] = fs.readFileSync(p, "utf8");
    if (f.endsWith(".png")) fs.copyFileSync(p, path.join(pubDir, f));
  }
}
// T24(제출·운영, 2026-10-28 전환) 2026 사후 표 — reports/experiments/contingency_T24/
for (const f of ["tbl_holdout_2026_posthoc_T24.md", "tbl_holdout_2026_posthoc_T24_detail.md"]) {
  const p = path.join(root, "reports", "experiments", "contingency_T24", f);
  if (fs.existsSync(p)) md[f] = fs.readFileSync(p, "utf8");
}
// 동결 문서: T24(제출·운영, FROZEN_T24.md) · 이력 v2.1(FROZEN_v2.1.md)·v1(FROZEN.md)·v2(FROZEN_v2.md)
for (const f of ["FROZEN.md", "FROZEN_v2.md", "FROZEN_v2.1.md", "FROZEN_T24.md"]) {
  const p = path.join(root, "models", f);
  if (fs.existsSync(p)) md[f] = fs.readFileSync(p, "utf8");
}
fs.mkdirSync(path.join(process.cwd(), "src", "generated"), { recursive: true });
fs.writeFileSync(path.join(process.cwd(), "src", "generated", "reports.json"), JSON.stringify(md));
console.log(`reports.json: ${Object.keys(md).length} md, png copied to public/reports`);
