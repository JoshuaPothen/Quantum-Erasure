"""Score every hair instance (score>=0.5, area>2000) of the given probes with tools/clip_id.py; draw sheet."""
import json, subprocess, sys, cv2, numpy as np
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
PY = r"C:/Users/POTHEN/AppData/Local/Comfy-Desktop/ComfyUI-Installs/ComfyUI/ComfyUI/.venv/Scripts/python.exe"
R = ROOT / "film" / "probe"
srv = subprocess.Popen([PY, str(ROOT / "tools" / "clip_id.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
cells = []
for f in map(int, sys.argv[2:]):
    rec = json.load(open(R / "inst" / f"f{f:06d}.json"))
    hs = [(j, h) for j, h in enumerate(rec["hair"]) if h["score"] >= 0.5 and h["area"] > 2000]
    srv.stdin.write(json.dumps({"img": str(R / "full" / f"f{f:06d}.jpg"), "boxes": [h["box"] for _, h in hs]}) + "\n")
    srv.stdin.flush()
    p = json.loads(srv.stdout.readline())["p"]
    im = cv2.resize(cv2.imread(str(R / "full" / f"f{f:06d}.jpg")), (480, 270), interpolation=cv2.INTER_AREA)
    for (j, h), pp in zip(hs, p):
        m = cv2.imread(str(R / "inst" / f"f{f:06d}_hair{j}.png"), 0) > 127
        c = (0, 255, 0) if pp > 0.5 else (0, 0, 255)
        cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(im, cs, -1, c, 2)
        ys, xs = np.nonzero(m)
        cv2.putText(im, f"P{pp:.2f}", (int(xs.min()), max(14, int(ys.min()) - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, c, 2)
    cv2.putText(im, str(f), (8, 262), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cells.append(im)
srv.stdin.close()
while len(cells) % 4:
    cells.append(np.zeros_like(cells[0]))
cv2.imwrite(sys.argv[1], np.vstack([np.hstack(cells[i:i + 4]) for i in range(0, len(cells), 4)]), [cv2.IMWRITE_JPEG_QUALITY, 80])
