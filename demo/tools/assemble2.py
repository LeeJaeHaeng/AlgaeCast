"""데모 영상 재조립 v2 (재녹화 없음, 기존 녹화 재사용).

변경점(사용자 검토 2026-10-21):
1) 녹화 화면을 90%(1728x972)로 축소해 상단 가운데(x=96, y=0)에 두고, 하단 108px 를 검은 자막 띠로 만든다. 자막은 띠 안에만.
2) 노트북 구간 오른쪽 아래의 어두운 사각형(=v1 에서 JupyterLab 'Jupyter news' 알림을 가리려고 칠한 drawbox)을 없애고,
   알림 자리를 주변과 같은 색(노트북 흰 바탕·세로 테두리·사이드바·하단 테두리)으로 채운다. ⑤ 구간은 원본에서 실시간으로 다시 자른다.
3) 0:00~0:08 타이틀 카드에는 자막을 넣지 않는다.
사용: python assemble2.py
"""

import json
import subprocess
from pathlib import Path

D = Path(__file__).resolve().parent
W = D / "work2"
W.mkdir(exist_ok=True)
FONTB = "C\\:/Windows/Fonts/malgunbd.ttf"
OUT = D / "AlgaeCast_demo.mp4"

SX, SY = 1728, 972  # 축소 화면
PX, PY = (1920 - SX) // 2, 0  # 배치 위치(상단 가운데)
BAND_Y = SY  # 972 ~ 1080 = 108px 자막 띠
FRAME = f"scale={SX}:{SY}:flags=lanczos,pad=1920:1080:{PX}:{PY}:black"

# JupyterLab 알림(x1585~1904, y958~1048) 자리를 주변 색으로 채움 (원본 1920x1080 좌표)
POPUP_FILL = ",".join(
    [
        "drawbox=x=1578:y=954:w=304:h=90:color=0xFFFFFF@1:t=fill",  # 노트북 흰 바탕 (x1578~1881, y954~1043)
        "drawbox=x=1578:y=1044:w=304:h=6:color=0xF3F3F3@1:t=fill",  # 노트북 하단 여백 줄 (y1044~1049)
        "drawbox=x=1578:y=1050:w=310:h=6:color=0xBCBCBC@1:t=fill",  # 패널 하단 테두리 (y1050~1055)
        "drawbox=x=1882:y=954:w=6:h=96:color=0xBCBCBC@1:t=fill",  # 패널 세로 테두리 (x1882~1887)
        "drawbox=x=1888:y=954:w=24:h=102:color=0xEDEDED@1:t=fill",  # 오른쪽 사이드바 (x1888~1911)
    ]
)


def run(cmd):
    subprocess.run(cmd, check=True)


def seg(src, start, end, target, path, fast=False, popup=False):
    dur = max(0.05, end - start)
    vf = [f"setpts={target / dur:.6f}*PTS", "fps=30"]
    if popup:
        vf.append(POPUP_FILL)
    if fast:
        vf.append(
            f"drawtext=fontfile='{FONTB}':text='⏩ 빨리감기 x{dur / target:.0f}':fontsize=34:fontcolor=white"
            ":box=1:boxcolor=0x000000AA:boxborderw=12:x=w-text_w-40:y=36"
        )
    vf += [FRAME, "format=yuv420p"]
    run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{dur:.3f}",
            "-i",
            str(src),
            "-vf",
            ",".join(vf),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "16",
            str(path),
        ]
    )


def reframe(src, path):
    """이미 만든 1920x1080 카드(엔딩)를 같은 틀(90% + 자막 띠)로."""
    run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vf",
            f"{FRAME},format=yuv420p",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "16",
            str(path),
        ]
    )


parts = []
# --- 타이틀 2장: v1 그대로(전체 화면, 자막 없음)
parts += [D / "work" / "t1.mp4", D / "work" / "t2.mp4"]

# --- 1부 노트북
cj = json.load(open(D / "rec_nb" / "cells.json", encoding="utf-8"))
nbv = cj["video"]
code = [c for c in cj["cells"] if c["isCode"]]
imp, ver, load, feat, train, hold, sub = code[:7]
plan = [  # (start, end, target_sec, fast)
    (ver["start"] - 1, ver["end"] + 2, 8, False),  # ① 봉인 모델 검증
    (load["start"], load["end"], 9, True),  # ② 로드·정렬
    (feat["start"], train["start"] - 0.2, 8, True),  # ③ 특징 — 셀이 끝나 화면이 넘어가기 직전(727.4s)까지
    (
        train["start"],
        827.2,
        6,
        True,
    ),  # ④-a 학습(빨리감기) — 원본 827.5~828.5 의 순서 어긋난 프레임 이전에서 끊음
    (829.0, 833.0, 4, False),  # ④-b 2025 검증표가 화면에 고정된 실시간 4초
    (923.6, 931.6, 8, False),  # ⑤ submission — 재실행([*]) 이후 결과가 고정된 실시간 8초(원본 화면 확인)
]
for k, (s, e, tgt, fast) in enumerate(plan):
    p = W / f"nb{k}.mp4"
    # 프레임별 알림 자리 복원(nbfill.py) — 고정 색 칠하기 대신 행별 주변 배경 중앙값
    run(
        [
            "python",
            str(D / "nbfill.py"),
            str(nbv),
            f"{s:.3f}",
            f"{e - s:.3f}",
            str(tgt),
            str(p),
            "1" if (fast and (e - s) > tgt * 1.5) else "0",
        ]
    )
    parts.append(p)

# --- 2부 운영 화면
scenes = {s["name"]: s for s in json.load(open(D / "rec_web3" / "scenes.json", encoding="utf-8"))}
for name, tgt, fast in [
    ("main", 8, 0),
    ("banner", 8, 0),
    ("tile", 10, 0),
    ("map", 6, 0),
    ("site", 8, 0),
    ("why", 8, 0),
    ("history", 8, 0),
    ("perf", 8, 0),
    ("bars", 8, 0),
    ("target", 4, 0),
    ("kiosk", 5, 1),
    ("score", 9, 0),
]:
    s = scenes[name]
    p = W / f"web_{name}.mp4"
    # 페이지 로드 흰 화면을 건너뛰고 정확한 프레임 수로(webseg.py)
    run(["python", str(D / "webseg.py"), str(s["path"]), str(s["seconds"]), str(tgt), str(p), str(fast)])
    parts.append(p)
# 엔딩 카드: 타이틀 카드와 같이 녹화 화면이 아니므로 전체 화면 그대로(축소·자막 없음)
parts.append(D / "work" / "end.mp4")

lst = W / "list.txt"
lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
run(
    [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(lst),
        "-c",
        "copy",
        str(W / "joined.mp4"),
    ]
)


# --- 자막: SRT → ASS (PlayRes 1920x1080 = 픽셀 단위). 0~8초(타이틀) 항목 제외, 띠 중앙(960, 1026)에 고정
def ts(t):
    h, m, s = t.split(":")
    s, ms = s.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def ass_t(x):
    h = int(x // 3600)
    m = int(x % 3600 // 60)
    s = x % 60
    return f"{h}:{m:02d}:{s:05.2f}"


blocks = [b for b in (D / "subs.srt").read_text(encoding="utf-8").strip().split("\n\n") if b.strip()]
ONE, TWO = 64, 40  # 한 줄 = v1 글자 크기(17 @ 288 = 63.75px) 유지, 두 줄 = 띠(108px) 안에 맞는 크기
events = []
for b in blocks:
    lines = b.strip().split("\n")
    a, z = [ts(x.strip()) for x in lines[1].split("-->")]
    if a < 8.0 or a >= 141.0:  # 타이틀 카드(0~8초)·엔딩 카드(2:21~) 구간: 화면 글자와 중복이라 자막 없음
        continue
    text = lines[2:]
    size = ONE if len(text) == 1 else TWO
    events.append(
        f"Dialogue: 0,{ass_t(a)},{ass_t(z)},Band,,0,0,0,,{{\\an5\\pos(960,{BAND_Y + 54})\\fs{size}}}"
        + "\\N".join(text)
    )
ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Band,Malgun Gothic,{TWO},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,20,20,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(events) + "\n"
(D / "subs_band.ass").write_text(ass, encoding="utf-8")
assp = (D / "subs_band.ass").as_posix().replace(":", "\\:")
run(
    [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(W / "joined.mp4"),
        "-vf",
        f"ass='{assp}'",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(OUT),
    ]
)
print("OUT", OUT, "events", len(events))
