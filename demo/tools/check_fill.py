"""알림 창 채움 검증: 사용한 원본 노트북 프레임 전부(10fps)에 nbfill.fill() 을 적용해,
알림 창 자체(불투명 사각형 x1586~1903, y959~1047) 바깥에서 눈에 보이게(채널 차 > 40) 바뀐 픽셀을 센다.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

D = Path(__file__).resolve().parent
src = (D / "nbfill.py").read_text(encoding="utf-8")
consts = src[: src.index("def decode():")]
fill_part = src[src.index("# 알림 그림자") : src.index("vf = []")]
sys.argv = ["nbfill.py", "x", "0", "1", "1", "x.mp4", "0"]
g = {"__file__": str(D / "nbfill.py")}
exec(consts, g)
exec(fill_part, g)
fill = g["fill"]

c = json.load(open(D / "rec_nb" / "cells.json", encoding="utf-8"))
code = [x for x in c["cells"] if x["isCode"]]
imp, ver, load, feat, train, hold, sub = code[:7]
wins = [
    ("①", ver["start"] - 1, ver["end"] + 2),
    ("②", load["start"], load["end"]),
    ("③", feat["start"], train["start"] - 0.2),
    ("④a", train["start"], 827.2),
    ("④b", 829.0, 833.0),
    ("⑤", 923.6, 931.6),
]
W, H = 1920, 1080
outside = np.ones((H, W), bool)
outside[956:1051, 1583:1907] = False  # 알림 창 + 테두리 + 그림자(녹화에서도 이미 가려져 있던 곳)
rim = np.zeros((H, W), bool)
rim[956:1051, 1583:1907] = True
rim[959:1048, 1586:1904] = False  # 알림 창 바깥 2~3px 테두리·그림자 띠
for name, s, e in wins:
    p = subprocess.Popen(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-ss",
            f"{s:.3f}",
            "-t",
            f"{e - s:.3f}",
            "-i",
            c["video"],
            "-vf",
            "fps=10",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        stdout=subprocess.PIPE,
    )
    k, changed = 0, []
    while True:
        b = p.stdout.read(W * H * 3)
        if len(b) < W * H * 3:
            break
        a = np.frombuffer(b, np.uint8).reshape(H, W, 3)
        f = fill(a)
        d = np.abs(f.astype(np.int16) - a.astype(np.int16)).max(axis=2)
        m = (d > 40) & outside
        lum = a.astype(np.int16).mean(axis=2)
        lost = (d > 40) & rim & (lum < 150)  # 띠 안에 있던 어두운(글자·아이콘) 픽셀이 지워진 경우
        n, nl = int(m.sum()), int(lost.sum())
        if n or nl:
            ys, xs = np.where(m | lost)
            changed.append(
                (round(s + k / 10, 1), n, nl, int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max()))
            )
        k += 1
    print(
        name,
        "frames",
        k,
        "frames with change outside popup+rim or dark pixels lost in rim:",
        len(changed),
        changed[:4],
    )
