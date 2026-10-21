import { TERMS } from "@/lib/copy";

/** ⓘ 용어 설명 — 마우스 올림/포커스 시 툴팁(순수 CSS, 키보드 접근 가능) */
export function Info({ term, text, className = "" }: { term?: keyof typeof TERMS; text?: string; className?: string }) {
  const tip = text ?? (term ? TERMS[term].tip : "");
  if (!tip) return null;
  return (
    <span className={`group relative inline-block align-middle ${className}`}>
      <button type="button" className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full border border-current text-[10px] leading-none text-dim opacity-80 hover:opacity-100 focus:opacity-100" aria-label={`설명: ${tip}`}>
        i
      </button>
      <span role="tooltip" className="pointer-events-none absolute left-1/2 top-full z-50 mt-1 w-64 -translate-x-1/2 rounded-lg border border-border bg-panel p-2 text-left text-xs font-normal leading-relaxed text-text opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        {tip}
      </span>
    </span>
  );
}

/** 용어 + ⓘ */
export function Term({ term, children }: { term: keyof typeof TERMS; children?: React.ReactNode }) {
  return (
    <span className="inline-flex items-center">
      {children ?? TERMS[term].label}
      <Info term={term} />
    </span>
  );
}
