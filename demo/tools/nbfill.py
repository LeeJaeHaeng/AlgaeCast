"""노트북 녹화 구간 처리 v3.

1) 프레임 순서 이상 제거: Playwright 녹화(webm)에 시간 순서가 어긋난 짧은 프레임 묶음(≤8프레임)이 섞여 있다
   (예: 셀 실행 전인데 submission 결과가 잠깐 보였다 사라짐). 앞뒤 프레임이 서로 같고 그 사이만 다른 짧은 묶음은
   직전 프레임으로 대체한다(2패스: 1패스 서명 계산 → 2패스 기록).
2) JupyterLab 'Jupyter news' 알림(원본 x1585~1904, y959~1047 + 그림자) 자리만 주변 구조대로 복원한다.
   - 행마다 왼쪽 이웃(x1480~1577) 중앙값 색 = 그 행의 배경(코드 셀 회색·출력 흰색·stderr 분홍·가로 테두리)
   - x1865 코드 셀 오른쪽 테두리(코드 행일 때), x1866~1880 흰 여백, x1871 선택된 셀 외곽선(파란 회색, 있을 때),
     x1881~1887 패널 세로 테두리, x1888~1911 사이드바, y1044 이후는 패널 하단(행 중앙값)
   - 채우는 범위는 알림 자체(그림자 포함)만: y956~, x1583~ — 바로 위 글자(제목 '비교' 등)는 건드리지 않는다.
3) 빨리감기 배지(▶▶, Malgun Gothic 에 있는 글리프), 90% 축소 + 하단 108px 자막 띠, 정확히 round(target*30) 프레임.
사용: python nbfill.py <src.webm> <start> <dur> <target_sec> <out.mp4> <fast:0|1>
"""

import subprocess
import sys

import numpy as np

src, start, dur, target, out, fast = (
    sys.argv[1],
    float(sys.argv[2]),
    float(sys.argv[3]),
    float(sys.argv[4]),
    sys.argv[5],
    sys.argv[6] == "1",
)
W, H = 1920, 1080
N = int(round(target * 30))
FONTB = "C\\:/Windows/Fonts/malgunbd.ttf"
FRAME = "scale=1728:972:flags=lanczos,pad=1920:1080:96:0:black"
Y0, Y1, YB = 956, 1056, 1044
X0 = 1583
SEL = np.array([90, 123, 128], np.int16)  # 선택 셀 외곽선 색(대략)


def decode():
    p = subprocess.Popen(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{dur + 0.5:.3f}",
            "-i",
            src,
            "-vf",
            f"setpts={target / dur:.6f}*PTS,fps=30",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        stdout=subprocess.PIPE,
    )
    n = W * H * 3
    k = 0
    while k < N:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).reshape(H, W, 3)
        k += 1
    p.stdout.close()
    p.wait()


def sig(a):
    g = a[:950, 290:1860].mean(axis=2)  # 노트북 본문(알림·배지 제외에 가깝게)
    return g.reshape(50, 19, 157, 10).mean(axis=(1, 3))


# --- 1패스: 서명 → 이상 묶음 찾기
sigs = [sig(a) for a in decode()]
d = lambda i, j: float(np.abs(sigs[i] - sigs[j]).mean())
replace = set()
i = 1
while i < len(sigs):
    hit = False
    if d(i, i - 1) > 4.0:
        for L in range(1, 9):
            j = i + L
            if j >= len(sigs):
                break
            if d(j - 1, j) > 4.0 and (d(i - 1, j) < 1.5 or L <= 6):
                # A→(짧은 B)→A 되돌아감, 또는 A→(짧은 B)→C 로 B 가 앞뒤 어느 쪽과도 다른 섬광 → 직전 프레임 유지
                replace.update(range(i, j))
                i = j
                hit = True
                break
    if not hit:
        i += 1


# 알림 그림자(채움 영역 바깥 위쪽 2~6행·왼쪽 3~6열) 보정: 그림자 = 배경 × (1-α) 이므로 녹화 전반 픽셀별 최댓값으로 α 를 추정해 되돌림
_MX = np.load(str(__import__("pathlib").Path(__file__).with_name("shadow_max.npy"))).astype(
    np.float32
)  # rows 944..1057, cols 1568..1911
_SY, _SX = 944, 1568
_GAIN = np.ones_like(_MX)
_band = np.zeros_like(_MX, dtype=bool)
_band[950 - _SY : Y0 - _SY, 1576 - _SX : 1881 - _SX] = (
    True  # 위쪽 그림자 띠(행 950~955) — 노트북 영역만(사이드바는 늘 237 이라 최댓값 추정이 안 맞음)
)
_band[950 - _SY : 1050 - _SY, 1576 - _SX : X0 - _SX] = True  # 왼쪽 그림자 띠(열 1576~1582)
_ok = _band & (_MX >= 232) & (_MX < 254.5)
_GAIN[_ok] = 255.0 / _MX[_ok]


def fill(a):
    a = a.copy()
    reg = a[_SY : _SY + _MX.shape[0], _SX : _SX + _MX.shape[1]].astype(np.float32)
    a[_SY : _SY + _MX.shape[0], _SX : _SX + _MX.shape[1]] = np.clip(
        reg * _GAIN[:, :, None] + 0.5, 0, 255
    ).astype(np.uint8)
    a[950:Y0, 1881:1888] = 188  # 그림자 띠 안의 패널 세로 테두리·사이드바는 고유색으로
    a[950:Y0, 1888:1912] = 237
    med = np.median(a[Y0:Y1, 1480:1578], axis=1).astype(np.int16)  # (rows,3)
    rows = Y1 - Y0
    # 기본: 행 배경
    a[Y0:Y1, X0:1866] = med[:, None, :].astype(np.uint8)
    a[Y0:YB, 1866:1881] = 255
    a[YB:Y1, 1866:1881] = med[YB - Y0 :, None, :].astype(np.uint8)
    a[Y0:Y1, 1881:1888] = 188
    a[Y0:Y1, 1888:1912] = 237
    # 코드 셀 행(회색 배경 ≈244, 흰색과 구분): 오른쪽 테두리 x1865
    grey = np.abs(med - 244).max(axis=1) <= 3
    for r in np.where(grey[: YB - Y0])[0]:
        a[Y0 + r, 1865] = (223, 223, 223)
    # 선택된 셀 외곽선: 위에서 이어져 내려오거나(밴드 바로 위 x1871 이 파란 회색), 밴드 안 파란 가로 테두리에서 시작
    is_sel_row = (np.abs(med - SEL).max(axis=1) < 40) & (med[:, 2] > med[:, 0] + 15)
    inside = bool(
        (a[Y0 - 3 : Y0, 1871].astype(np.int16)[:, 2] > a[Y0 - 3 : Y0, 1871].astype(np.int16)[:, 0] + 15).all()
    )
    prev = False
    for r in range(0, YB - Y0):
        if is_sel_row[r]:
            a[Y0 + r, X0:1872] = med[r].astype(np.uint8)  # 가로 테두리를 x1871 까지
            if not prev:
                inside = not inside  # 위 테두리 → 안으로, 아래 테두리 → 밖으로
        if inside or is_sel_row[r]:
            a[Y0 + r, 1871] = SEL.astype(np.uint8)
        prev = bool(is_sel_row[r])
    # 세로선(위 30행 동안 같은 색으로 곧게 내려오는 열) 연장 — 셀 아래 테두리 행에서 멈춤
    above = a[Y0 - 30 : Y0, X0:1881].astype(np.int16)
    line = above[-1]
    steady = np.abs(above - line[None]).max(axis=(0, 2)) < 24
    painted = a[Y0, X0:1881].astype(np.int16)
    differs = np.abs(line - painted).sum(axis=1) > 60
    for xi in np.where(steady & differs)[0]:
        col = line[xi].astype(np.uint8)
        for y in range(Y0, YB):
            a[y, X0 + xi] = col
            if np.abs(med[y - Y0] - line[xi]).sum() < 40:
                break
    return a


vf = []
if fast:
    vf.append(
        f"drawtext=fontfile='{FONTB}':text='▶▶ 빨리감기 x{dur / target:.0f}':fontsize=32:fontcolor=white"
        ":box=1:boxcolor=0x000000AA:boxborderw=12:x=w-text_w-40:y=36"
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
last = None
written = 0
for k, a in enumerate(decode()):
    if k in replace and last is not None:
        a = last
    else:
        a = fill(a)
        last = a
    enc.stdin.write(a.tobytes())
    written += 1
while written < N and last is not None:  # 부족하면 마지막 프레임으로 채움
    enc.stdin.write(last.tobytes())
    written += 1
enc.stdin.close()
enc.wait()
print(out, "frames", written, "replaced", sorted(replace)[:20], "count", len(replace))
