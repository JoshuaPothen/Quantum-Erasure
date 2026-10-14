#!/usr/bin/env python3
"""
QC sheets for gradual-transition detection. Frames are fetched by film index
through tools/frameio.py (short seek windows, so only seconds per sample).

  docs/img/01_qc_dissolves_v2.jpg        every detected dissolve: start | 1/3 | 2/3 | end
  docs/img/01_qc_dissolve_rejected.jpg   stage-1 runs rejected by stage 2 inside the
                                         forest (7:50) and stylised (41:34) long shots

Usage: python tools/dissolve_qc.py <video>
"""
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from frameio import iter_frames, FPS  # noqa: E402

video = sys.argv[1]
IMG = Path("docs/img")
# --sample N [--seed S] [--extra START-END ...]: random sample of story-region
# detections (plus specific runs) into docs/img/01_qc_dissolves_sample.jpg
SAMPLE = int(sys.argv[sys.argv.index("--sample") + 1]) if "--sample" in sys.argv else 0
SEED = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 11
EXTRA = [tuple(map(int, a.split("-"))) for i, a in enumerate(sys.argv) if i and sys.argv[i - 1] == "--extra"]


def frames_at(indices):
    want, got = set(indices), {}
    lo, hi = min(want), max(want)
    for idx, fr in iter_frames(video, width=320, start_s=lo / FPS - 0.5, end_s=hi / FPS + 0.2):
        if idx in want:
            got[idx] = fr.copy()
    return got


def label(im, f, note=""):
    im = im.copy() if im is not None else np.zeros((180, 320, 3), np.uint8)
    cv2.rectangle(im, (0, 0), (320, 22), (0, 0, 0), -1)
    cv2.putText(im, f"{f}  {f/FPS/60:.0f}:{f/FPS%60:05.2f}", (4, 16), 0, 0.5, (255, 255, 255), 1)
    if note:
        cv2.rectangle(im, (0, 158), (320, 180), (0, 0, 0), -1)
        cv2.putText(im, note, (4, 175), 0, 0.5, (0, 255, 255), 1)
    return im


def sheet(rows, path, title):
    sep = np.full((180, 4, 3), 255, np.uint8)
    body = np.vstack([np.hstack([np.hstack([t, sep]) for t in r]) for r in rows])
    head = np.zeros((40, body.shape[1], 3), np.uint8)
    cv2.putText(head, title, (8, 28), 0, 0.7, (255, 255, 255), 2)
    cv2.imwrite(str(path), np.vstack([head, body]), [cv2.IMWRITE_JPEG_QUALITY, 85])
    print("wrote", path, f"({len(rows)} rows)")


def row_for(s, e, tag):
    picks = [s, s + (e - s) // 3, s + 2 * (e - s) // 3, e]
    got = frames_at(picks)
    notes = [f"{tag} start ({e-s+1} fr)", "1/3", "2/3", "end"]
    return [label(got.get(f), f, n) for f, n in zip(picks, notes)]


diss = [(int(r["start_frame"]), int(r["end_frame"])) for r in csv.DictReader(open("shots/dissolves_v2.csv"))]
if SAMPLE:
    import random
    random.seed(SEED)
    story = [d for d in diss if 10200 < d[0] < int(75.5 * 60 * FPS)]
    pick = EXTRA + sorted(random.sample(story, min(SAMPLE, len(story))))
    sheet([row_for(s, e, "check" if (s, e) in EXTRA else "diss") for s, e in pick],
          IMG / "01_qc_dissolves_sample.jpg",
          f"story-region detections: {len(story)} total, {SAMPLE} random (seed {SEED}) + {len(EXTRA)} checked  [start | 1/3 | 2/3 | end]")
    sys.exit(0)
sheet([row_for(s, e, "diss") for s, e in diss], IMG / "01_qc_dissolves_v2.jpg",
      f"detected dissolves/fades: all {len(diss)}  [start | 1/3 | 2/3 | end]")

rej = [(int(r["start_frame"]), int(r["end_frame"]), r["global_blend"], r["alpha_drop"])
       for r in csv.DictReader(open("shots/dissolve_candidates.csv"))
       if r["is_dissolve"] == "0" and (11280 <= int(r["start_frame"]) <= 11808 or 58368 <= int(r["start_frame"]) <= 58896)]
rows = []
for s, e, gb, dr in rej[:10]:
    r = row_for(s - 2, e + 2, f"rej gb{gb} dr{dr}")
    rows.append(r)
if rows:
    sheet(rows, IMG / "01_qc_dissolve_rejected.jpg",
          f"stage-1 runs rejected by stage 2 in the 7:50 and 41:34 long shots: {len(rej)} (<=10 shown)")
else:
    print("no rejected stage-1 runs inside those long shots")
