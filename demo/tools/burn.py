import subprocess
from pathlib import Path

D = Path(__file__).resolve().parent
W = D / "work2"
OUT = D / "AlgaeCast_demo.mp4"
BAND_Y = 972


def run(cmd):
    subprocess.run(cmd, check=True)


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
