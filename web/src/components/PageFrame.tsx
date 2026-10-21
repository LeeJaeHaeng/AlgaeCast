import Link from "next/link";
import { APP, BOARD } from "@/lib/copy";

/** 메인 상황판 외 페이지의 공통 틀: 상단 바(제목·메뉴·보기 전환) + 본문 + 바닥 출처 */
export function PageFrame({ title, lead, expert, children, back }: { title: string; lead?: string; expert: boolean; children: React.ReactNode; back?: { href: string; label: string } }) {
  const q = expert ? "?view=expert" : "";
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-40 flex h-14 items-center gap-4 border-b border-border bg-panel/95 px-4 backdrop-blur">
        <Link href={`/${q}`} className="text-lg font-bold tracking-tight">
          {APP.title}
        </Link>
        <nav aria-label="주 메뉴" className="flex items-center gap-1.5 text-sm">
          {APP.nav.map((n) => (
            <Link key={n.href} href={`${n.href}${q}`} className="btn" aria-current={n.label === title ? "page" : undefined}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {back && (
            <Link href={`${back.href}${q}`} className="btn">
              {back.label}
            </Link>
          )}
          <Link href={expert ? "?" : "?view=expert"} className="btn" aria-pressed={expert}>
            {expert ? BOARD.btn.easy : BOARD.btn.expert}
          </Link>
        </div>
      </header>
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
