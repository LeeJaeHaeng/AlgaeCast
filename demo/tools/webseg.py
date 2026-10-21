"""운영 화면(웹) 장면 처리: 페이지 로드 중 흰 화면·밝기 전환 구간을 건너뛰고 정확히 round(target*30) 프레임으로 기록.

- 시작점: 장면 녹화에서 화면이 어두워진 뒤(평균 밝기 < 110) 밝기가 안정된(0.5초 뒤와 차이 < 1.5) 첫 시점
- 그 이후에도 흰 프레임(평균 밝기 > 170, 순환 모드의 페이지 이동 등)은 직전 프레임으로 대체
- 녹화가 모자라면 마지막 프레임으로 채움, 빨리감기면 배지(▶▶) 표시, 90% 축소 + 하단 108px 자막 띠
사용: python webseg.py <src.webm> <avail_sec(=장면 길이)> <target_sec> <out.mp4> <fast:0|1>
"""

import subprocess
import sys

import numpy as np

src, seconds, target, out, fast = (
    sys.argv[1],
    float(sys.argv[2]),
    float(sys.argv[3]),
    sys.argv[4],
    sys.argv[5] == "1",
)
W, H = 1920, 1080
N = int(round(target * 30))
FONTB = "C\\:/Windows/Fonts/malgunbd.ttf"
FRAME = "scale=1728:972:flags=lanczos,pad=1920:1080:96:0:black"


def lum_series(path, fps=10):
    p = subprocess.Popen(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            path,
            "-vf",
            f"fps={fps},scale=192:108",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        stdout=subprocess.PIPE,
    )
    vals = []
    while True:
        b = p.stdout.read(192 * 108)
        if len(b) < 192 * 108:
            break
        vals.append(float(np.frombuffer(b, np.uint8).mean()))
    p.wait()
    return vals


L = lum_series(src)
# 장면 녹화 = 흰 화면(로드) → 부분 렌더 → 완전 렌더 → (강조 장면) 나머지를 어둡게 하는 강조 적용.
# 1초 이상 밝기가 일정한 구간(plateau) 중, 흰 화면 이후 6초 안에 시작하는 가장 어두운 구간의 시작점을 쓴다
# → 강조 장면은 강조가 켜진 순간부터, 강조 없는 장면(메인·순환)은 완전히 그려진 화면부터 시작.
first_dark = next((i for i, x in enumerate(L) if x < 110), 0)
plateaus = []
i = first_dark
while i < len(L):
    j = i
    while j + 1 < len(L) and abs(L[j + 1] - L[i]) < 1.5:
        j += 1
    if j - i + 1 >= 10 and L[i] < 110:
        plateaus.append((i, L[i]))
    i = j + 1
cands = [pl for pl in plateaus if pl[0] <= first_dark + 60]
# 가장 어두운 값에서 3 이내인 구간 중 가장 이른 것(두 번 강조하는 장면은 첫 강조부터)
if cands:
    lo = min(pl[1] for pl in cands)
    t_start = min(pl[0] for pl in cands if pl[1] <= lo + 3) / 10 + 0.1
else:
    t_start = first_dark / 10 + 0.1
total = len(L) / 10
avail = total - t_start
dur = min(seconds, avail)  # 원래 장면 길이만큼(가능하면) 사용
factor = target / seconds  # 순환 모드처럼 압축할 때 같은 비율 유지

dec = subprocess.Popen(
    [
        "ffmpeg",
        "-loglevel",
        "error",
        "-ss",
        f"{t_start:.3f}",
        "-t",
        f"{dur:.3f}",
        "-i",
        src,
        "-vf",
        f"setpts={factor:.6f}*PTS,fps=30",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ],
    stdout=subprocess.PIPE,
)
vf = []
if fast:
    # 운영 화면은 오른쪽 위에 시계·'순환 끝내기' 버튼이 있어 배지를 위쪽 가운데에 둔다
    vf.append(
        f"drawtext=fontfile='{FONTB}':text='▶▶ 빨리감기 x{1 / factor:.0f}':fontsize=32:fontcolor=white"
        ":box=1:boxcolor=0x000000AA:boxborderw=12:x=(w-text_w)/2:y=36"
    )
vf += [FRAME, "format=yuv420p"]
enc = subprocess.Popen(
    [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{W}x{H}",
        "-r",
        "30",
        "-i",
        "-",
        "-vf",
        ",".join(vf),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "16",
        "-frames:v",
        str(N),
        out,
    ],
    stdin=subprocess.PIPE,
)
n = W * H * 3
last, written, swapped = None, 0, 0
while written < N:
    b = dec.stdout.read(n)
    if len(b) < n:
        break
    a = np.frombuffer(b, np.uint8).reshape(H, W, 3)
    if last is not None and a[::8, ::8].mean() > 170:  # 흰 화면(페이지 이동 중) → 직전 프레임
        a = last
        swapped += 1
    enc.stdin.write(a.tobytes())
    last = a
    written += 1
padded = 0
while written < N and last is not None:
    enc.stdin.write(last.tobytes())
    written += 1
    padded += 1
enc.stdin.close()
enc.wait()
dec.wait()
print(
    out, f"start {t_start:.1f}s of {total:.1f}s, frames {written}, white-swapped {swapped}, padded {padded}"
)
