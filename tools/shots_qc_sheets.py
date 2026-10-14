#!/usr/bin/env python3
"""
Build visual QC sheets for shot detection from shots/thumbs320 (frame-exact
thumbnails from tools/grab_frames.py). Each sheet answers one question:

  01_qc_missed_by_adaptive.jpg   cuts content27 finds but adaptive3 doesn't: real cuts adaptive misses?
  01_qc_only_adaptive.jpg        cuts only adaptive3 finds: real, or false positives?
  01_qc_burst_content20.jpg      runs of minimum-length (8-frame) content20 shots: real fast cutting, or motion?
  01_qc_dissolves.jpg            candidate gradual transitions: before | middle | after
  01_qc_longest_adaptive.jpg     frames every ~2 s inside adaptive3's longest shots: hidden cuts?

Each row = one sample: [frame before | frame after] (or 3-6 frames), labelled
with the 0-based frame index and film time.  Samples are drawn with a fixed
seed so sheets are reproducible.

Usage: python tools/shots_qc_sheets.py [--method adaptive3]
"""
import csv
import random
import sys
from pathlib import Path

import cv2
import numpy as np

FPS = 24000 / 1001
T = Path("shots/thumbs320")
IMG = Path("docs/img")
random.seed(7)


def load_cuts(m):
    return [int(r["start_frame"]) for r in csv.DictReader(open(f"shots/cuts_{m}.csv"))][1:]


def shots(m):
    return [(int(r["start_frame"]), int(r["end_frame"])) for r in csv.DictReader(open(f"shots/cuts_{m}.csv"))]


def thumb(f, note=""):
    p = T / f"f{f:06d}.jpg"
    im = cv2.imread(str(p)) if p.exists() else None
    if im is None:
        im = np.zeros((180, 320, 3), np.uint8)
        cv2.putText(im, "missing", (100, 95), 0, 0.8, (0, 0, 255), 2)
    im = im.copy()
    lab = f"{f}  {f/FPS/60:.0f}:{f/FPS%60:05.2f}"
    cv2.rectangle(im, (0, 0), (320, 22), (0, 0, 0), -1)
    cv2.putText(im, lab, (4, 16), 0, 0.5, (255, 255, 255), 1)
    if note:
        cv2.rectangle(im, (0, 158), (320, 180), (0, 0, 0), -1)
        cv2.putText(im, note, (4, 175), 0, 0.5, (0, 255, 255), 1)
    return im


def sheet(rows, path, title):
    w = max(len(r) for r in rows)
    pad = lambda r: r + [np.full((180, 320, 3), 40, np.uint8)] * (w - len(r))
    body = np.vstack([np.hstack([np.hstack([t, np.full((180, 4, 3), 255, np.uint8)]) for t in pad(r)])
                      for r in rows])
    head = np.zeros((40, body.shape[1], 3), np.uint8)
    cv2.putText(head, title, (8, 28), 0, 0.75, (255, 255, 255), 2)
    cv2.imwrite(str(path), np.vstack([head, body]), [cv2.IMWRITE_JPEG_QUALITY, 85])
    print("wrote", path, f"({len(rows)} rows)")


def near(x, arr, tol=2):
    return any(abs(x - a) <= tol for a in arr)


method = sys.argv[sys.argv.index("--method") + 1] if "--method" in sys.argv else "adaptive3"
c27, c20, ad = load_cuts("content27"), load_cuts("content20"), load_cuts(method)
credits = int(75.5 * 60 * FPS)  # end credits start ~75.5 min (flat content_val in 01_content_val_full.png)

# 1. cuts content27 has that the adaptive list lacks
miss = [c for c in c27 if not near(c, ad) and c < credits]
smp = sorted(random.sample(miss, min(16, len(miss))))
rows = [[thumb(c - 1, "before"), thumb(c, "after")] for c in smp]
# two per row to keep the sheet compact
rows = [rows[i] + rows[i + 1] if i + 1 < len(rows) else rows[i] for i in range(0, len(rows), 2)]
sheet(rows, IMG / "01_qc_missed_by_adaptive.jpg",
      f"content27 cuts NOT in {method}: {len(miss)} total, 16 sampled  [before | after] x2")

# 2. cuts only the adaptive list has
only = [c for c in ad if not near(c, c27) and c < credits]
smp = sorted(random.sample(only, min(12, len(only))))
rows = [[thumb(c - 1, "before"), thumb(c, "after")] for c in smp]
rows = [rows[i] + rows[i + 1] if i + 1 < len(rows) else rows[i] for i in range(0, len(rows), 2)]
sheet(rows, IMG / "01_qc_only_adaptive.jpg",
      f"{method} cuts NOT in content27: {len(only)} total, 12 sampled  [before | after] x2")

# 3. bursts of minimum-length shots in content20 (>=3 consecutive 8..9-frame shots)
s20 = shots("content20")
bursts, run = [], []
for s, e in s20:
    if e - s + 1 <= 9:
        run.append(s)
    else:
        if len(run) >= 3:
            bursts.append(run)
        run = []
smp = random.sample(bursts, min(6, len(bursts)))
rows = [[thumb(f, "cut?") for f in sorted(b)[:5]] for b in sorted(smp)]
sheet(rows, IMG / "01_qc_burst_content20.jpg",
      f"content20 bursts of >=3 consecutive 8-9 frame shots: {len(bursts)} bursts, 6 sampled (each frame = a 'cut')")

# 4. candidate dissolves
dis = [(int(r["start_frame"]), int(r["end_frame"])) for r in csv.DictReader(open("shots/dissolves.csv"))]
dis = [d for d in dis if d[0] < credits]
smp = sorted(random.sample(dis, min(10, len(dis))))
rows = [[thumb(s - 2, "before"), thumb((s + e) // 2, f"mid ({e-s+1} fr)"), thumb(e + 2, "after")] for s, e in smp]
rows = [rows[i] + rows[i + 1] if i + 1 < len(rows) else rows[i] for i in range(0, len(rows), 2)]
sheet(rows, IMG / "01_qc_dissolves.jpg",
      f"candidate dissolves (content_val elevated >=8 frames, never a hard cut): {len(dis)} total, 10 sampled")

# 5. longest adaptive shots outside the credits: look for hidden cuts
long = sorted([(e - s + 1, s, e) for s, e in shots(method) if s < credits], reverse=True)[:6]
rows = []
for n, s, e in long:
    fs = [f for f in range(0, 116734, 48) if s <= f <= e]
    pick = [fs[round(i * (len(fs) - 1) / 5)] for i in range(6)] if len(fs) >= 6 else fs
    rows.append([thumb(f, f"shot {n/FPS:.1f}s" if i == 0 else "") for i, f in enumerate(pick)])
sheet(rows, IMG / "01_qc_longest_adaptive.jpg",
      f"{method}: 6 longest shots before the credits, 6 frames spread across each")
