import { InfoTip } from "@/components/InfoTip";
import { TERMS } from "@/lib/copy";

/** ⓘ 용어 설명 — 문구를 정해 InfoTip(마우스 올림/포커스 시 툴팁, 화면 안 위치 보정)에 넘긴다 */
export function Info({ term, text, className = "" }: { term?: keyof typeof TERMS; text?: string; className?: string }) {
  const tip = text ?? (term ? TERMS[term].tip : "");
  if (!tip) return null;
  return <InfoTip tip={tip} className={className} />;
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
