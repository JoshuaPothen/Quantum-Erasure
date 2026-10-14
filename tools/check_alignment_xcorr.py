#!/usr/bin/env python3
"""
Robust drift measurement: cross-correlate the detector's per-frame change
signal (stats content_val, mapped to 0-based = FrameNumber-1) with OpenCV's
own sequential frame-diff signal (shots/opencv_diff.npy), in 2-minute
segments, over lags of +-MAXLAG frames.  lag L means: the event the stats
put at index i is at OpenCV index i+L.
Writes shots/alignment_lags.csv and docs/img/01_alignment_xcorr.png.
"""
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FPS = 24000 / 1001
SEG, MAXLAG = int(120 * FPS), 240
d = np.nan_to_num(np.load("shots/opencv_diff.npy"))
rows = list(csv.reader(open("shots/stats.csv")))[1:]
def f(x):
    try: return float(x)
    except ValueError: return 0.0
s = np.zeros(max(int(r[0]) for r in rows) + 1)
for r in rows:
    s[int(r[0]) - 1] = f(r[3])
n = min(len(s), len(d))
s, d = s[:n], d[:n]
# spike-ify both signals: change relative to local median, so only cuts dominate
def spikes(x):
    from numpy.lib.stride_tricks import sliding_window_view
    pad = np.pad(x, 12, mode="edge")
    med = np.median(sliding_window_view(pad, 25), axis=1)[:len(x)]
    y = np.clip(x - med, 0, None)
    return y / (y.std() + 1e-9)
S, D = spikes(s), spikes(d)
out = []
for a in range(0, n - SEG, SEG // 2):
    seg = S[a:a + SEG]
    if seg.max() < 3:
        continue
    best, bl, scores = -1, 0, []
    for L in range(-MAXLAG, MAXLAG + 1):
        lo, hi = a + L, a + L + SEG
        if lo < 0 or hi > n:
            scores.append(np.nan); continue
        c = float(np.dot(seg, D[lo:hi]) / (np.linalg.norm(seg) * np.linalg.norm(D[lo:hi]) + 1e-9))
        scores.append(c)
        if c > best:
            best, bl = c, L
    sc = np.array(scores); second = np.nanmax(np.where(np.abs(np.arange(-MAXLAG, MAXLAG + 1) - bl) > 2, sc, np.nan))
    out.append((a, bl, best, second))
with open("shots/alignment_lags.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["seg_start_frame", "seg_start_min", "lag", "corr", "next_best_corr"])
    for a, L, c, c2 in out:
        w.writerow([a, f"{a/FPS/60:.2f}", L, f"{c:.3f}", f"{c2:.3f}"])
for a, L, c, c2 in out:
    print(f"{a/FPS/60:5.1f} min  lag {L:+4d}  corr {c:.2f}  (next {c2:.2f})")
o = np.array(out)
fig, ax = plt.subplots(figsize=(12, 3.2))
ax.plot(o[:, 0] / FPS / 60, o[:, 1], marker="o", ms=3, color="#2c3e50")
ax.set_xlabel("film time (min)"); ax.set_ylabel("lag (frames)")
ax.set_title("OpenCV index minus detector index (FrameNumber-1), per 2-min segment (cross-correlation)")
ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig("docs/img/01_alignment_xcorr.png", dpi=110)
