"""Overlay sheet of probe frames from film/probe/probe_sam3.csv: hair green, her (woman:1) red outline,
all women (woman:4) blue outline. Usage: python checks/probe_sheet.py <out.jpg> <film_idx> ..."""
import sys, cv2, numpy as np
from pathlib import Path
R = Path(__file__).resolve().parent.parent / "film" / "probe"
cells = []
for f in sys.argv[2:]:
    f = int(f)
    im = cv2.resize(cv2.imread(str(R / "full" / f"f{f:06d}.jpg")), (480, 270), interpolation=cv2.INTER_AREA)
    m = {k: cv2.imread(str(R / "masks" / f"f{f:06d}_{k}.png"), 0) > 127 for k in ("hair", "w1", "w4")}
    im[m["hair"]] = (0.4 * im[m["hair"]] + [0, 150, 0]).astype(np.uint8)
    for k, c in (("w4", (255, 120, 0)), ("w1", (0, 0, 255))):
        cs, _ = cv2.findContours(m[k].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(im, cs, -1, c, 2)
    cv2.putText(im, str(f), (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cells.append(im)
while len(cells) % 4:
    cells.append(np.zeros_like(cells[0]))
cv2.imwrite(sys.argv[1], np.vstack([np.hstack(cells[i:i + 4]) for i in range(0, len(cells), 4)]), [cv2.IMWRITE_JPEG_QUALITY, 80])
