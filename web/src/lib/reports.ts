import reports from "../generated/reports.json";

/** reports/eval·eda 의 markdown 표 — scripts/sync-reports.mjs 가 빌드 전에 src/generated/reports.json 으로 묶는다(런타임 fs 불필요). */
export function readReport(name: string): string | null {
  return (reports as Record<string, string>)[name] ?? null;
}

export type MdTable = { header: string[]; rows: string[][] };

export function parseTables(md: string): { title: string; table: MdTable }[] {
  const lines = md.split(/\r?\n/);
  const out: { title: string; table: MdTable }[] = [];
  let title = "";
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (l.startsWith("#")) title = l.replace(/^#+\s*/, "");
    if (l.startsWith("|") && lines[i + 1]?.startsWith("|---")) {
      const header = l.split("|").slice(1, -1).map((c) => c.trim());
      const rows: string[][] = [];
      let j = i + 2;
      while (lines[j]?.startsWith("|")) {
        rows.push(lines[j].split("|").slice(1, -1).map((c) => c.trim()));
        j++;
      }
      out.push({ title, table: { header, rows } });
      i = j;
    }
  }
  return out;
}

export function firstParagraphs(md: string, n = 6): string[] {
  return md
    .split(/\r?\n/)
    .filter((l) => l.startsWith("- ") || l.startsWith("**"))
    .slice(0, n)
    .map((l) => l.replace(/^- /, "").replace(/\*\*/g, ""));
}

/** models/FROZEN.md(v1, 수정 전 이력)·FROZEN_v2.md(v2, 수정 전 이력) 의 동결 커밋 7자리 (reports.json 사본) — v2.1 커밋은 numbers.ts MODELS */
export function frozenCommit(file: "FROZEN.md" | "FROZEN_v2.md" = "FROZEN.md"): string {
  const md = readReport(file) ?? "";
  const m = md.match(/동결 커밋: `([0-9a-f]+)`/);
  return m ? m[1].slice(0, 7) : "–";
}
