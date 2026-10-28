"""완성 영상 옛 문구 프레임 검사.
1) 0.5초 간격 프레임 → 2배 확대 PNG(화면 영역)·자막 띠 PNG 따로
2) Windows OCR(ko) → 프레임별 글자
3) 공백·구두점을 지운 뒤 옛 문구(정확·근사) 검색, 새 문구(T24·057afeee·사후 계산) 출현 구간 기록
사용: python scan_old.py <video.mp4> <work_dir>
"""

import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

VID, WORK = Path(sys.argv[1]), Path(sys.argv[2])
FR = WORK / "frames"
FR.mkdir(parents=True, exist_ok=True)
PS1 = Path(__file__).with_name("ocr_frames.ps1")  # 같은 폴더의 Windows OCR(ko) 스크립트(UTF-8 BOM)

if not any(FR.glob("*.png")):
    raw = WORK / "raw"
    raw.mkdir(exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", str(VID), "-vf", "fps=2", str(raw / "f_%04d.png")],
        check=True,
    )
    for p in sorted(raw.glob("f_*.png")):
        i = int(p.stem.split("_")[1]) - 1  # f_0001 = 0.0초 부근(fps 필터는 0.25초 중심)
        im = Image.open(p)
        im.crop((0, 0, 1920, 972)).resize((3840, 1944), Image.LANCZOS).save(FR / f"s_{i:04d}.png")
        im.crop((0, 972, 1920, 1080)).save(FR / f"b_{i:04d}.png")
        p.unlink()

out = WORK / "ocr.txt"
if not out.exists():
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PS1),
            "-Dir",
            str(FR),
            "-Out",
            str(out),
        ],
        check=True,
    )

texts: dict[str, str] = {}
cur = None
for line in out.read_text(encoding="utf-8").splitlines():
    if line.startswith("=== "):
        cur = line[4:].strip()
        texts[cur] = ""
    elif cur:
        texts[cur] += line + "\n"


def norm(s: str) -> str:
    return re.sub(r"[\s·•ㆍ.,:;'\"()\[\]{}|\-—–~]+", "", s)


OLD = [
    "발령발령",
    "2025년까지자료로",
    "2025년까지자료로만만든",
    "만든v2.1로",
    "제출모델v2.1",
    "v2.1기준",
    "4741a3d3",
    "20261021녹화",
]
NEW = ["T24", "057afeee", "사후계산", "2024년까지자료로만"]
OLD, NEW = [norm(o) for o in OLD], [norm(k) for k in NEW]  # 검색어도 같은 규칙으로(점·하이픈 제거)
hits, near, newseen = [], [], {k: [] for k in NEW}
for name, s in sorted(texts.items()):
    kind, idx = name[0], int(name[2:6])
    t = idx / 2
    n = norm(s)
    for o in OLD:
        if o in n:
            hits.append((t, kind, o))
        else:
            # 근사: 같은 길이 창에서 유사도 0.85 이상
            L = len(o)
            for j in range(0, max(0, len(n) - L) + 1):
                if difflib.SequenceMatcher(None, n[j : j + L], o).ratio() >= 0.85:
                    near.append((t, kind, o, n[j : j + L]))
                    break
    for k in NEW:
        if k in n:
            newseen[k].append(t)

res = {
    "frames": len({k[2:6] for k in texts}),
    "ocr_images": len(texts),
    "old_exact": hits,
    "old_near": near,
    "new_seen_seconds": {k: sorted(set(v)) for k, v in newseen.items()},
}
(WORK / "scan_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("frames", res["frames"], "ocr images", res["ocr_images"])
print("old exact", len(hits), hits[:20])
print("old near", len(near), near[:20])
for k, v in res["new_seen_seconds"].items():
    print(k, len(v), (v[:3], v[-3:]) if v else "")
