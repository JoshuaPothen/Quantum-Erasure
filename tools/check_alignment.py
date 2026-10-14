#!/usr/bin/env python3
"""
Measure frame-index offset between PySceneDetect's stats (shots/stats.csv,
1-based 'Frame Number') and OpenCV sequential indices (shots/opencv_diff.npy
from tools/frame_diff_scan.py), at every strong cut across the film.

For each strong stats cut F (content_val >= 40) the true OpenCV index of the
first new frame is taken as the argmax of opencv_diff within F-1 +- 6.
offset = that index - (F - 1); 0 means pass 2's mapping is exact.

Writes docs/img/01_alignment_offset.png and prints offset runs over time.
"""
import csv

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FPS = 24000 / 1001
d = np.load("shots/opencv_diff.npy")
rows = list(csv.reader(open("shots/stats.csv")))[1:]


def f(x):
    try:
        return float(x)
    except ValueError:
        return np.nan


fn = np.array([int(r[0]) for r in rows])
cv = np.array([f(r[3]) for r in rows])
strong = fn[cv >= 40]
W = 6
pts = []
for F in strong:
    c = F - 1
    lo, hi = max(c - W, 1), min(c + W + 1, len(d))
    if hi <= lo:
        continue
    win = d[lo:hi]
    if not np.isfinite(win).any():
        continue
    k = lo + int(np.nanargmax(win))
    # only trust clear peaks: the peak must stand well above the window's median
    if win[k - lo] < 3 * np.nanmedian(win) + 5:
        continue
    pts.append((c, k - c))
pts = np.array(pts)
print(f"{len(strong)} strong stats cuts, {len(pts)} with a clear OpenCV peak")
vals, cnt = np.unique(pts[:, 1], return_counts=True)
print("offset histogram:", dict(zip(vals.tolist(), cnt.tolist())))

# runs of constant offset (smoothed by majority over 9 neighbouring cuts)
from collections import Counter
sm = [Counter(pts[max(0, i - 4):i + 5, 1].tolist()).most_common(1)[0][0] for i in range(len(pts))]
runs, start = [], 0
for i in range(1, len(sm) + 1):
    if i == len(sm) or sm[i] != sm[start]:
        runs.append((int(pts[start, 0]), int(pts[i - 1, 0]), int(sm[start]), i - start))
        start = i
print("offset runs (first_frame, last_frame, offset, n_cuts):")
for a, b, o, n in runs:
    print(f"  frames {a:6d}-{b:6d}  ({a/FPS/60:5.1f}-{b/FPS/60:5.1f} min)  offset {o:+d}  [{n} cuts]")

fig, ax = plt.subplots(figsize=(12, 3))
ax.scatter(pts[:, 0] / FPS / 60, pts[:, 1], s=6, alpha=0.5, color="#2c3e50")
ax.plot(pts[:, 0] / FPS / 60, sm, color="#c0392b", lw=1.2, label="majority of 9 neighbouring cuts")
ax.set_xlabel("film time (min)"); ax.set_ylabel("OpenCV index - (FrameNumber-1)")
ax.set_title("Frame-index offset between detector stats and OpenCV sequential read, per strong cut")
ax.set_yticks(range(-W, W + 1)); ax.legend(fontsize=8); ax.grid(alpha=0.3)
fig.tight_layout(); fig.savefig("docs/img/01_alignment_offset.png", dpi=110)
print("wrote docs/img/01_alignment_offset.png")
