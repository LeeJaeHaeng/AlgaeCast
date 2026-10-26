import Link from "next/link";
import { APP, BOARD } from "@/lib/copy";

/**
 * 메인 상황판 외 페이지의 공통 틀: 상단 바(제목·메뉴·보기 전환) + 본문 + 바닥 출처.
 * 다시 보기(지점 상세·상황 기록 ?asof): top = 맨 위 띠(상단 바와 함께 위에 붙음), homeQuery = 메인으로 가는 링크 쿼리(asof 유지),
 * expertHref = 보기 전환 링크(asof 유지). 셋 다 없으면 기본 화면과 같은 마크업.
 */
export function PageFrame({ title, lead, expert, children, back, className, top, homeQuery, expertHref }: { title: string; lead?: string; expert: boolean; children: React.ReactNode; back?: { href: string; label: string }; className?: string; top?: React.ReactNode; homeQuery?: string; expertHref?: string }) {
  const q = expert ? "?view=expert" : "";
  const hq = homeQuery ?? q;
  const header = (
    <header className={top ? "flex h-14 items-center gap-4 border-b border-border bg-panel/95 px-4 backdrop-blur" : "sticky top-0 z-40 flex h-14 items-center gap-4 border-b border-border bg-panel/95 px-4 backdrop-blur"}>
      <Link href={`/${hq}`} className="text-lg font-bold tracking-tight">
        {APP.title}
      </Link>
      <nav aria-label="주 메뉴" className="flex items-center gap-1.5 text-sm">
        {APP.nav.map((n) => (
          <Link key={n.href} href={`${n.href}${n.href === "/" ? hq : q}`} className="btn" aria-current={n.label === title ? "page" : undefined}>
            {n.label}
          </Link>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-2">
        {back && (
          <Link href={`${back.href}${back.href === "/" ? hq : q}`} className="btn">
            {back.label}
          </Link>
        )}
        <Link href={expertHref ?? (expert ? "?" : "?view=expert")} className="btn" data-active={expert ? "true" : undefined}>
          {expert ? BOARD.btn.easy : BOARD.btn.expert}
        </Link>
      </div>
    </header>
  );
  return (
    <div className={className ? `min-h-dvh ${className}` : "min-h-dvh"}>
      {top ? (
        <div className="sticky top-0 z-40">
          {top}
          {header}
        </div>
      ) : (
        header
      )}
      <main className="mx-auto max-w-[1880px] space-y-3 p-3">
        {(title || lead) && (
          <div className="flex flex-wrap items-baseline gap-3">
            <h1 className="text-2xl font-bold">{title}</h1>
            {lead && <p className="text-base text-dim">{lead}</p>}
          </div>
        )}
        {children}
      </main>
      <footer className="px-4 py-4 text-xs text-dim">{APP.footer}</footer>
    </div>
  );
}
