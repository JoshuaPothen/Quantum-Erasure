"""Instance sheet for probes (film/probe/inst): each hair instance with score >= MIN outlined and
labelled 'score/dark'; women (score >= 0.5) thin blue. Usage: probe_inst_sheet.py <out.jpg> <min> <idx>..."""
import sys, json, cv2, numpy as np
from pathlib import Path
R = Path(__file__).resolve().parent.parent / "film" / "probe"
CO = [(0, 255, 0), (0, 200, 255), (255, 0, 255), (0, 0, 255)]
mn = float(sys.argv[2])
cells = []
for f in map(int, sys.argv[3:]):
    im = cv2.resize(cv2.imread(str(R / "full" / f"f{f:06d}.jpg")), (480, 270), interpolation=cv2.INTER_AREA)
    rec = json.load(open(R / "inst" / f"f{f:06d}.json"))
    for j, w in enumerate(rec["woman"]):
        if w["score"] >= 0.5:
            m = cv2.imread(str(R / "inst" / f"f{f:06d}_woman{j}.png"), 0)
            cs, _ = cv2.findContours((m > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(im, cs, -1, (255, 120, 0), 1)
    k = 0
    for j, h in enumerate(rec["hair"]):
        if h["score"] < mn:
            continue
        m = cv2.imread(str(R / "inst" / f"f{f:06d}_hair{j}.png"), 0) > 127
        c = CO[k % 4]; k += 1
        cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(im, cs, -1, c, 2)
        ys, xs = np.nonzero(m)
        if len(xs):
            cv2.putText(im, f"{h['score']:.2f}/{h['dark']:.2f}", (int(xs.min()), max(14, int(ys.min()) - 3)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 2)
    cv2.putText(im, str(f), (8, 262), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cells.append(im)
while len(cells) % 4:
    cells.append(np.zeros_like(cells[0]))
cv2.imwrite(sys.argv[1], np.vstack([np.hstack(cells[i:i + 4]) for i in range(0, len(cells), 4)]), [cv2.IMWRITE_JPEG_QUALITY, 80])
