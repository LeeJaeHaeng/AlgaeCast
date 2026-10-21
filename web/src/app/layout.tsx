import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "AlgaeCast-7 — 7일 녹조 예측·취수원 운영 대시보드",
  description: "수질·수문·기상 융합 기반 댐·하천 유해남조류 7일 예측과 2단계(감시/경보) 운영 지원",
};

const NAV = [
  { href: "/", label: "홈" },
  { href: "/performance", label: "성능" },
  { href: "/insights", label: "인사이트" },
  { href: "/about", label: "소개" },
];

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko" data-theme="light">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
            <Link href="/" className="text-lg font-bold tracking-tight">
              AlgaeCast-7 <span className="ml-2 text-xs font-normal text-slate-500">7일 녹조 예측 · 취수원 운영</span>
            </Link>
            <nav aria-label="주 메뉴" className="flex gap-1 text-sm">
              {NAV.map((n) => (
                <Link key={n.href} href={n.href} className="rounded px-3 py-1.5 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">
                  {n.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
        <footer className="mx-auto max-w-7xl px-4 py-8 text-xs text-slate-500">
          2026 DATA·AI 분석 경진대회 — 데이터: 국립환경과학원 조류경보제·K-water·WAMIS·DataON·기상청 (공공누리). 예측은 운영 참고용이며 공식 발령을 대체하지 않습니다.
        </footer>
      </body>
    </html>
  );
}
