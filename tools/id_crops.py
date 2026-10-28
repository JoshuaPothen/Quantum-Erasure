#!/usr/bin/env python3
"""Labelling sheets for the identity classifier (film/README step 5).
Every probe hair instance with SAM3 score >= 0.6 and area >= 4000 px gets an id; crops (the same
square crop tools/clip_id.py embeds) are tiled 8 x 5 per sheet with the id printed on each.
Usage: python tools/id_crops.py <sheet_start> <n_sheets> [--seed 0]
Writes film/id/sheets/sheet_<k>.jpg and film/id/instances.csv (id, film_idx, inst, score, box)."""
import csv, json, random, sys
from pathlib import Path
import cv2, numpy as np
ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "film" / "probe"
D = ROOT / "film" / "id"
(D / "sheets").mkdir(parents=True, exist_ok=True)
inst_csv = D / "instances.csv"
# ids are stable: probes finished later are shuffled and appended after the existing rows
old = list(csv.DictReader(open(inst_csv))) if inst_csv.exists() else []
seen = {(int(r["film_idx"]), int(r["inst"])) for r in old}
new = []
for jf in sorted((R / "inst").glob("f*.json")):
    for j, h in enumerate(json.load(open(jf))["hair"]):
        if h["score"] >= 0.6 and h["area"] >= 4000 and (int(jf.stem[1:]), j) not in seen:
            new.append([int(jf.stem[1:]), j, h["score"]] + h["box"])
random.Random(len(old)).shuffle(new)
with open(inst_csv, "a" if old else "w", newline="") as f:
    w = csv.writer(f)
    if not old:
        w.writerow(["id", "film_idx", "inst", "score", "x", "y", "w", "h"])
    w.writerows([[len(old) + i] + r for i, r in enumerate(new)])
rows = list(csv.DictReader(open(inst_csv)))
if sys.argv[1] == "--ids":   # active-learning sheets: python tools/id_crops.py --ids <file> <name>
    pick = [rows[int(i)] for i in open(sys.argv[2]).read().split()]
    name = sys.argv[3]
    groups = [(f"{name}_{k}", pick[k * 40:(k + 1) * 40]) for k in range((len(pick) + 39) // 40)]
else:
    k0, nk = int(sys.argv[1]), int(sys.argv[2])
    groups = [(f"sheet_{k:03d}", rows[k * 40:(k + 1) * 40]) for k in range(k0, k0 + nk)]
for gname, grp in groups:
    cells = []
    for r in grp:
        im = cv2.imread(str(R / "full" / f"f{int(r['film_idx']):06d}.jpg"))
        x, y, w, h = (float(r[c]) for c in "xywh")
        s = max(w, h) * 1.7
        cx, cy = x + w / 2, y + h / 2
        H, W = im.shape[:2]
        c = im[int(max(0, cy - s / 2)):int(min(H, cy + s / 2)), int(max(0, cx - s / 2)):int(min(W, cx + s / 2))]
        c = cv2.resize(c, (220, 220), interpolation=cv2.INTER_AREA)
        m = cv2.imread(str(R / "inst" / f"f{int(r['film_idx']):06d}_hair{r['inst']}.png"), 0)
        m = cv2.resize(m, (W, H))[int(max(0, cy - s / 2)):int(min(H, cy + s / 2)), int(max(0, cx - s / 2)):int(min(W, cx + s / 2))]
        cs, _ = cv2.findContours((cv2.resize(m, (220, 220)) > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(c, cs, -1, (0, 255, 0), 1)
        cv2.rectangle(c, (0, 0), (62, 24), (0, 0, 0), -1)
        cv2.putText(c, r["id"], (3, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
        cells.append(c)
    if not cells:
        break
    while len(cells) % 8:
        cells.append(np.zeros_like(cells[0]))
    cv2.imwrite(str(D / "sheets" / f"{gname}.jpg"),
                np.vstack([np.hstack(cells[i:i + 8]) for i in range(0, len(cells), 8)]), [cv2.IMWRITE_JPEG_QUALITY, 85])
print(len(rows), "instances")
