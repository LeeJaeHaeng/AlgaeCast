import type { Metadata, Viewport } from "next";
import { APP } from "@/lib/copy";
import "./globals.css";

export const metadata: Metadata = {
  title: APP.title,
  description: `${APP.subtitle} — ${APP.competition}`,
};
export const viewport: Viewport = { themeColor: "#0A1020", width: "device-width", initialScale: 1 };

/** 발표모드(밝은 테마)를 첫 그리기 전에 적용해 깜빡임 방지 */
const THEME_SCRIPT = `try{if(localStorage.getItem("algaecast.theme")==="light")document.documentElement.dataset.theme="light"}catch(e){};(function(){var l=document.getElementById("pretendard");if(!l)return;var f=function(){l.media="all"};l.addEventListener("load",f);setTimeout(f,1500)})();`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko" data-theme="dark">
      <head>
        <link rel="preload" as="style" crossOrigin="anonymous" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" />
        <link id="pretendard" rel="stylesheet" media="print" crossOrigin="anonymous" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" />
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
