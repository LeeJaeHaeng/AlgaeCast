// 쉽게 보기 금지어 자동 검사 (docs/12 §7·§10): 실행 중인 서버의 페이지를 받아 보이는 텍스트에서 영어 약어·내부 변수명을 찾는다.
// 사용: node scripts/check_copy.mjs http://localhost:3300 [/ /sites/2011G26 ...]  → reports/screenshots/banned_words_check.md
import { writeFileSync, mkdirSync } from "node:fs";

// src/lib/copy.ts 의 BANNED_EASY 와 동일하게 유지할 것
const BANNED = ["q50", "q10", "q90", "p_alert", "cqr", "shap", "oof", "lightgbm", "nnls", "tweedie", "hurdle", "optuna", "r²", "r2", "nse", "rmse", "mae", "f1", "picp", "auc", "cells/ml", "base_date", "target_date", "tier", "watch_flag", "alert_flag", "site_id", "run_id", "p ≥", "q90 ≥", "isotonic", "smearing", "expanding"];
const base = process.argv[2] ?? "http://localhost:3300";
const paths = process.argv.length > 3 ? process.argv.slice(3) : ["/"];

function visibleText(html) {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&[a-z]+;/gi, " ")
    .replace(/\s+/g, " ");
}
const lines = [`# 쉽게 보기 금지어 검사 — ${new Date().toISOString().slice(0, 16)}`, "", `기준: ${base}, 금지어 ${BANNED.length}개`, ""];
let total = 0;
for (const p of paths) {
  const html = await (await fetch(base + p)).text();
  const text = visibleText(html).toLowerCase();
  const hits = [];
  for (const w of BANNED) {
    const re = new RegExp(`(^|[^a-z0-9_])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![a-z0-9_])`, "g");
    const m = text.match(re);
    if (m) hits.push(`${w}×${m.length}`);
  }
  total += hits.length;
  lines.push(`- ${p}: ${hits.length ? hits.join(", ") : "0건"}`);
}
lines.push("", `합계 ${total}건`);
mkdirSync("../reports/screenshots", { recursive: true });
writeFileSync("../reports/screenshots/banned_words_check.md", lines.join("\n") + "\n", "utf-8");
console.log(lines.join("\n"));
process.exit(total ? 1 : 0);
