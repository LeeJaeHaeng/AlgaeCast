"""v2 자동 점검: 최종본(자막) vs joined(자막 없음) 0.5초 간격 비교."""

import subprocess
from pathlib import Path

import numpy as np

D = Path(__file__).resolve().parent
FIN, RAW = D / "AlgaeCast_demo.mp4", D / "work2" / "joined.mp4"
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


issues, stats = [], []
for i, (f, r) in enumerate(zip(frames(FIN), frames(RAW))):
    t = i / FPS
    diff = np.abs(f.astype(np.int16) - r.astype(np.int16)).max(axis=2)
    above = float((diff[:BAND] > 60).mean())
    if not (t < 8.0 or t >= 141.0) and above > 2e-4:
        issues.append(f"{t:6.1f}s 자막이 띠 위로 침범 의심: 띠 위 변화 픽셀 비율 {above:.5f}")
    band_f = f[BAND:].max(axis=2)
    band_r = r[BAND:].max(axis=2)
    card = t < 8.0 or t >= 141.0
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
    # 옛 검은 사각형 자리(원본 x1580~1910, y950~1050 → 축소 후 x1518~1815, y855~945): 노트북 구간 8~51초
    if 8.0 <= t < 51.0:
        reg = f[858:943, 1520:1812].astype(np.int16)
        dark = float((reg.max(axis=2) < 80).mean())
        if dark > 0.02:
            issues.append(f"{t:6.1f}s 알림 자리 어두운 픽셀 {dark:.3f}")

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
