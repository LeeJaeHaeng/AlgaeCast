"""데모 영상 조립 v3 (2026-10-22, 제출 모델 v2 반영).

- 1부(노트북): v2 패키지 노트북을 새로 녹화한 영상(cells.json)에서 구간을 자른다. JupyterLab 뉴스 알림을 설정으로 꺼서
  알림 창이 없으므로 nbfill.py 의 알림 자리 채우기는 끄고(NBFILL_NOPOPUP=1) 프레임 순서 정리·배지·축소만 쓴다.
- 2부(운영 화면): 숫자가 바뀐 장면(perf·target·score)만 2026-10-22 재녹화본을 쓰고, 나머지 장면은 2026-10-21 녹화본
  (demo/raw/web_scenes)을 그대로 쓴다.
- 타이틀·엔딩 카드: 숫자가 없는 카드라 v1 영상(2026-10-21)의 0~8초·2:21~2:28 을 그대로 잘라 쓴다.
- 자막: subs_v2.srt(시간 배치는 v1 과 같고 문구만 v2 반영), 띠 위치·크기는 assemble2.py 와 같다.
사용: python assemble3.py <work_dir> <cells.json> <old_web_dir> <new_scenes.json> <subs.srt> <cards_dir> <out.mp4>
  구간 시각(④-b 2025 표, ⑤ submission)은 NB_HOLD=<s,e> NB_SUB=<s,e> 환경변수로 준다(원본 화면 확인 후).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

D = Path(__file__).resolve().parent
W, CELLS, OLD_WEB, NEW_SCENES, SUBS, CARDS, OUT = (Path(a) for a in sys.argv[1:8])
W.mkdir(parents=True, exist_ok=True)
BAND_Y = 972


def run(cmd: list[str], env: dict | None = None) -> None:
    subprocess.run(cmd, check=True, env=env)


parts = [CARDS / "t1.mp4", CARDS / "t2.mp4"]

# --- 1부 노트북
cj = json.load(open(CELLS, encoding="utf-8"))
nbv = cj["video"]
code = [c for c in cj["cells"] if c["isCode"]]
imp, ver, load, feat, train, hold, sub = code[:7]
hs, he = (float(x) for x in os.environ["NB_HOLD"].split(","))
ss, se = (float(x) for x in os.environ["NB_SUB"].split(","))
plan = [  # (start, end, target_sec)
    (ver["start"] - 1, ver["end"] + 2, 8),  # ① 봉인 모델 검증
    (load["start"], load["end"] + 1.0, 9),  # ② 로드·정렬(약 0.85배)
    (feat["start"], train["start"] - 0.2, 8),  # ③ 특징
    (train["start"], train["end"] + 2.2, 6),  # ④-a 학습 실행과 가중치 출력(빨리감기 약 2배)
    (hs, he, 4),  # ④-b 2025 검증표(실시간)
    (ss, se, 8),  # ⑤ submission(실시간)
]
env = {**os.environ, "NBFILL_NOPOPUP": "1"}
for k, (s, e, tgt) in enumerate(plan):
    p = W / f"nb{k}.mp4"
    fast = (e - s) > tgt * 1.5
    run(
        [
            sys.executable,
            str(D / "nbfill.py"),
            str(nbv),
            f"{s:.3f}",
            f"{e - s:.3f}",
            str(tgt),
            str(p),
            "1" if fast else "0",
        ],
        env=env,
    )
    parts.append(p)

# --- 2부 운영 화면
old = {s["name"]: s for s in json.load(open(OLD_WEB / "scenes.json", encoding="utf-8"))}
new = {s["name"]: s for s in json.load(open(NEW_SCENES, encoding="utf-8"))}
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
    s = new.get(name) or {**old[name], "path": str(OLD_WEB / old[name]["file"])}
    p = W / f"web_{name}.mp4"
    run(
        [sys.executable, str(D / "webseg.py"), str(s["path"]), str(s["seconds"]), str(tgt), str(p), str(fast)]
    )
    parts.append(p)
parts.append(CARDS / "end.mp4")

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


def ts(t: str) -> float:
    h, m, s = t.split(":")
    s, ms = s.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def ass_t(x: float) -> str:
    return f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}"


blocks = [b for b in SUBS.read_text(encoding="utf-8").strip().split("\n\n") if b.strip()]
ONE, TWO = 64, 40
events = []
for b in blocks:
    lines = b.strip().split("\n")
    a, z = [ts(x.strip()) for x in lines[1].split("-->")]
    if a < 8.0 or a >= 141.0:  # 타이틀·엔딩 카드 구간은 자막 없음
        continue
    text = lines[2:]
    size = ONE if len(text) == 1 else TWO
    events.append(
        f"Dialogue: 0,{ass_t(a)},{ass_t(z)},Band,,0,0,0,,{{\\an5\\pos(960,{BAND_Y + 54})\\fs{size}}}"
        + "\\N".join(text)
    )
ass = (
    "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
    "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
    "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    f"Style: Band,Malgun Gothic,{TWO},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,20,20,0,1\n\n"
    "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    + "\n".join(events)
    + "\n"
)
assf = W / "subs_band.ass"
assf.write_text(ass, encoding="utf-8")
assp = assf.as_posix().replace(":", "\\:")
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
