"""v7 자동 점검: 최종본(자막) vs joined(자막 없음) 0.5초 간격 비교 + 흰 화면 검사.
사용: python check_v7.py <final.mp4> <joined.mp4>
"""

import subprocess
import sys
from pathlib import Path

import numpy as np

FIN, RAW = Path(sys.argv[1]), Path(sys.argv[2])
W, H, FPS = 1920, 1080, 2
BAND = 972


def frames(path):
    p = subprocess.Popen(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            f"fps={FPS}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        stdout=subprocess.PIPE,
    )
    n = W * H * 3
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).reshape(H, W, 3)


issues, stats, white = [], [], []
for i, (f, r) in enumerate(zip(frames(FIN), frames(RAW))):
    t = i / FPS
    diff = np.abs(f.astype(np.int16) - r.astype(np.int16)).max(axis=2)
    above = float((diff[:BAND] > 60).mean())
    card = t < 8.0 or t >= 141.0
    if not card and above > 2e-4:
        issues.append(f"{t:6.1f}s 자막이 띠 위로 침범 의심: 띠 위 변화 픽셀 비율 {above:.5f}")
    band_f = f[BAND:].max(axis=2)
    band_r = r[BAND:].max(axis=2)
    if not card and band_r.max() > 24:
        issues.append(f"{t:6.1f}s 띠 안에 화면 내용 있음(자막 없는 원본 띠 최대 밝기 {band_r.max()})")
    rows = np.where((band_f > 140).any(axis=1))[0]
    cols = np.where((band_f > 140).any(axis=0))[0]
    if card:
        if (diff > 60).mean() > 2e-4:
            issues.append(f"{t:6.1f}s 카드 구간에 자막이 있음")
    elif len(rows):
        top, bot = BAND + rows.min(), BAND + rows.max()
        if top < BAND + 2 or bot > H - 2:
            issues.append(f"{t:6.1f}s 자막이 띠 가장자리에 닿음 y {top}~{bot}")
        stats.append((t, top, bot, int(cols.min()), int(cols.max())))
    elif not card:
        issues.append(f"{t:6.1f}s 자막 없음")
    # 운영 화면 구간(51~141초)의 흰 화면(로딩) 검사: 화면 영역 평균 밝기
    if 51.0 <= t < 141.0:
        m = float(f[:BAND, 96:1824].mean())
        if m > 200:
            white.append(t)
            issues.append(f"{t:6.1f}s 흰 화면 의심(평균 밝기 {m:.0f})")

print("frames checked:", i + 1)
print("issues:", len(issues))
for x in issues[:40]:
    print("  ", x)
if stats:
    tops = [s[1] for s in stats]
    bots = [s[2] for s in stats]
    print(
        f"subtitle text rows: top {min(tops)}~{max(tops)}, bottom {min(bots)}~{max(bots)}; x {min(s[3] for s in stats)}~{max(s[4] for s in stats)}; frames with text {len(stats)}"
    )
