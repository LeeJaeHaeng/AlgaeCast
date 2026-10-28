"""타이틀 카드 1(v1 영상에서 잘라 쓴 t1.mp4)의 작은 줄 '화면 수치는 2026-10-21 녹화 시점 기준' 의 날짜를 고친다(v7, 2026-10-28).

- 카드는 4초 정지 화면이다. 2초 지점 프레임 하나를 가져와 날짜 끝자리 '1' 한 글자 칸만 배경색으로 지우고
  같은 글꼴(맑은 고딕 24px — 원문 줄 폭 428px 와 같음)로 새 숫자를 그린다. 숫자 폭이 같아(13px) 나머지 글자는 그대로다.
- 결과 프레임으로 같은 형식(H.264 yuv420p 30fps, 120프레임)의 4초 영상을 만든다.
사용: python fix_title_card.py <t1.mp4> <out.mp4> <새 끝자리 숫자(예: 8)>
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SRC, OUT, DIGIT = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
OLD = "화면 수치는 2026-10-21 녹화 시점 기준"
LEFT, TOP = 745, 560  # 원문 줄의 글자 왼쪽·위 픽셀(1920×1080 카드 기준)
BG, FG = (9, 15, 32), (148, 163, 184)
FONT = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 24)

with tempfile.TemporaryDirectory() as td:
    frame = Path(td) / "f.png"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-ss", "2", "-i", str(SRC), "-frames:v", "1", str(frame)],
        check=True,
    )
    im = Image.open(frame).convert("RGB")
    a = np.asarray(im).copy()
    bb = FONT.getbbox(OLD)
    x0 = LEFT - bb[0] + FONT.getlength(OLD[: OLD.index("21 ") + 1])  # 끝자리 '1' 의 시작 x
    w = FONT.getlength("1")
    assert w == FONT.getlength(DIGIT), "숫자 폭이 달라 한 글자만 바꿀 수 없다"
    xa, xb = int(np.floor(x0)) - 1, int(np.ceil(x0 + w)) + 1
    before = (np.abs(a[TOP - 4 : TOP + 28, xa:xb].astype(int) - BG).max(axis=2) > 25).sum()
    a[TOP - 4 : TOP + 28, xa:xb] = BG
    im2 = Image.fromarray(a)
    ImageDraw.Draw(im2).text((x0, TOP - bb[1]), DIGIT, font=FONT, fill=FG)
    # 바뀐 범위가 그 한 글자 칸뿐인지 확인
    diff = np.abs(np.asarray(im2).astype(int) - np.asarray(im).astype(int)).max(axis=2) > 0
    ys, xs = np.where(diff)
    print(f"바꾼 칸 x {xs.min()}~{xs.max()}, y {ys.min()}~{ys.max()} (지운 글자 픽셀 {before})")
    assert xs.min() >= xa and xs.max() < xb and ys.min() >= TOP - 4 and ys.max() < TOP + 28
    fixed = Path(td) / "fixed.png"
    im2.save(fixed)
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(fixed),
            "-frames:v",
            "120",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-video_track_timescale",
            "15360",
            str(OUT),
        ],
        check=True,
    )
    im2.save(OUT.with_suffix(".png"))
print("OUT", OUT)
