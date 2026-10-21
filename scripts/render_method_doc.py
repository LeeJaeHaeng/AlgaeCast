# ruff: noqa: E501  (한국어 문구)
"""방법설명서 렌더링 (T9-a): reports/방법설명서.md → reports/방법설명서.html → reports/방법설명서.pdf.

- Markdown → HTML: mistune 3 (표·각주 플러그인). 그림 경로는 reports/ 기준 상대경로.
- HTML → PDF: 헤드리스 Edge(Chromium) --print-to-pdf (A4, 머리말·꼬리말 없음).
사용: python scripts/render_method_doc.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import mistune

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "reports"
MD = REP / "방법설명서.md"
HTML = REP / "방법설명서.html"
PDF = REP / "방법설명서.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

CSS = """
@page { size: A4; margin: 14mm 14mm 15mm 14mm; }
html { font-family: 'Malgun Gothic', '맑은 고딕', 'Apple SD Gothic Neo', sans-serif; font-size: 9pt; color: #111; }
p, li, h1, h2, h3, h4, .cover, blockquote { word-break: keep-all; overflow-wrap: break-word; }
td, th { word-break: normal; }
section.footnotes p, section.footnotes li { word-break: normal; overflow-wrap: anywhere; text-align: left; margin: 0; }
sup.footnote-ref + sup.footnote-ref::before { content: ","; }
body { line-height: 1.46; }
h1 { font-size: 22pt; margin: 0 0 6mm; }
h2 { font-size: 14pt; border-bottom: 2px solid #1f4e79; padding-bottom: 1.5mm; margin: 6mm 0 2.5mm; page-break-after: avoid; color: #1f4e79; }
h3 { font-size: 10.4pt; margin: 3.2mm 0 1.2mm; color: #1f4e79; page-break-after: avoid; }
h4 { font-size: 10.5pt; margin: 4mm 0 1.5mm; }
p, li { text-align: justify; margin: 0 0 1.4mm; }
table { border-collapse: collapse; width: 100%; margin: 2mm 0 3mm; font-size: 7.6pt; line-height: 1.33; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #9aa7b5; padding: 0.7mm 1.2mm; vertical-align: top; }
th { background: #e8eef5; }
img { display: block; max-width: 100%; max-height: 70mm; margin: 1.5mm auto 1mm; page-break-inside: avoid; }
.cap { text-align: center; font-size: 8.6pt; color: #444; margin: 0 0 4mm; }
code { font-family: Consolas, monospace; font-size: 8.8pt; background: #f3f5f8; padding: 0 1mm; }
pre { background: #f3f5f8; padding: 2.5mm; font-size: 8.5pt; white-space: pre-wrap; page-break-inside: avoid; }
blockquote { border-left: 3px solid #1f4e79; margin: 3mm 0; padding: 1mm 4mm; background: #f6f9fc; }
section.footnotes ol { columns: 2; column-gap: 6mm; padding-left: 6mm; margin: 0; }
section.footnotes li { margin: 0 0 0.6mm; text-align: left; }
section.footnotes { font-size: 6.6pt; line-height: 1.25; color: #333; border-top: 1px solid #bbb; margin-top: 6mm; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; }
.cover .sub { font-size: 13pt; color: #333; margin-bottom: 10mm; }
.cover .meta { font-size: 11pt; line-height: 2; }
.cover .head { margin-top: 12mm; padding: 5mm 6mm; border: 2px solid #1f4e79; border-radius: 3mm; font-size: 10.5pt; background: #f6f9fc; }
.toc { page-break-before: always; page-break-after: always; }
.toc h2 { page-break-before: avoid; }
.toc ol { list-style: none; }
.toc > ol { columns: 2; column-gap: 8mm; font-size: 10pt; line-height: 1.55; padding-left: 0; }
.toc > ol > li { font-weight: 600; }
.toc ol ol li { font-weight: 400; }
.toc > ol > li { break-inside: avoid; margin-bottom: 1.5mm; }
.toc ol ol { font-size: 8.6pt; line-height: 1.4; color: #333; padding-left: 5mm; }
"""


def toc(md: str) -> str:
    items: list[tuple[int, str]] = []
    for m in re.finditer(r"^(##|###) (.+)$", md, re.M):
        items.append((len(m.group(1)), m.group(2).strip()))
    out = ['<div class="toc"><h2>목차</h2><ol>']
    open_sub = False
    for lvl, t in items:
        if lvl == 2:
            if open_sub:
                out.append("</ol></li>")
                open_sub = False
            out.append(f"<li>{t}")
            out.append("<ol>")
            open_sub = True
        else:
            out.append(f"<li>{t}</li>")
    if open_sub:
        out.append("</ol></li>")
    out.append("</ol></div>")
    return "\n".join(out)


def main() -> int:
    md = MD.read_text(encoding="utf-8")
    cover_end = md.index("\n## ")
    cover_md, body_md = md[:cover_end], md[cover_end:]
    render = mistune.create_markdown(plugins=["table", "footnotes", "strikethrough"], escape=False)
    body = render(body_md)
    # 그림 아래 캡션(대체 텍스트)
    # 본문에 '*그림 x-y. …*' 캡션이 바로 뒤따르는 그림은 대체 텍스트 캡션을 생략한다(중복 방지).
    body = re.sub(
        r'(<img src="([^"]+)" alt="([^"]*)"\s*/?>)(?!\s*</p>\s*<p><em>그림)',
        r'\1<div class="cap">\3</div>',
        body,
    )
    cover = render(cover_md)
    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>AlgaeCast-7 방법설명서</title><style>{CSS}</style></head>
<body><div class="cover">{cover}</div>{toc(body_md)}{body}</body></html>"""
    HTML.write_text(html, encoding="utf-8")
    missing = [p for p in re.findall(r'<img src="([^"]+)"', html) if not (REP / p).exists()]
    if missing:
        print("그림 파일 없음:", missing)
        return 1
    # 헤드리스 전용·임시 프로필(창이 뜨지 않음). 끝나면 프로필을 지운다.
    import shutil
    import tempfile

    prof = Path(tempfile.mkdtemp(prefix="algaecast_pdf_"))
    try:
        r = subprocess.run(
            [
                str(EDGE),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={prof}",
                "--no-pdf-header-footer",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=20000",
                f"--print-to-pdf={PDF}",
                HTML.resolve().as_uri(),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    if not PDF.exists():
        print("PDF 생성 실패", r.stderr[-500:])
        return 1
    print(f"PDF {PDF} {PDF.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
