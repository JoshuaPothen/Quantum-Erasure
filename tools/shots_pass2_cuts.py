#!/usr/bin/env python3
"""
Shot detection, pass 2: turn pass-1 per-frame metrics into cut lists, offline.

No video decoding: reads shots/stats.csv only, so every threshold experiment
costs seconds. Cut rule (same as PySceneDetect's detectors, simplified):
  cut at frame i  if  metric[i] >= threshold  and  i - previous_cut >= min_len
Candidate dissolves are flagged separately: runs of >= DISS_MIN_RUN frames
where content_val stays elevated but never reaches a hard-cut threshold.

Usage: python tools/shots_pass2_cuts.py shots
Writes: shots/cuts_<method>.csv, shots/dissolves.csv, shots/pass2_summary.txt,
        docs/img/01_*.png plots
"""
import csv
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FPS = 24000 / 1001
MIN_LEN = 8            # frames (~0.33 s); film rarely cuts faster than this
DISS_LEVEL = 4.0       # content_val floor for "something is changing"
DISS_MIN_RUN = 8       # frames; a dissolve spans several frames

d = Path(sys.argv[1] if len(sys.argv) > 1 else "shots")
img = Path("docs/img")
img.mkdir(parents=True, exist_ok=True)

with open(d / "stats.csv", newline="") as f:
    rows = list(csv.reader(f))
hdr = rows[0]
col = {h: i for i, h in enumerate(hdr)}
print("columns:", hdr)
cv_col = col["content_val"]
ad_name = next(h for h in hdr if h.startswith("adaptive_ratio"))
frame_col = next(i for i, h in enumerate(hdr) if "Frame" in h)

# "Frame Number" in the stats CSV is 1-based (frame 2 is at 0.042s); convert
# to the 0-based index OpenCV's sequential read uses (tools/shots_thumbs.py).
frames = np.array([int(r[frame_col]) - 1 for r in rows[1:]])
def num(r, i):
    try:
        return float(r[i])
    except (ValueError, IndexError):
        return np.nan
content = np.array([num(r, cv_col) for r in rows[1:]])
adaptive = np.array([num(r, col[ad_name]) for r in rows[1:]])
N = len(frames)
print(f"{N} frames, content_val non-NaN {np.isfinite(content).sum()}, adaptive non-NaN {np.isfinite(adaptive).sum()}")


def cuts_from(metric, thr, extra=None):
    out, last = [], -10**9
    for i in range(N):
        m = metric[i]
        if np.isfinite(m) and m >= thr and (extra is None or extra[i]) and i - last >= MIN_LEN:
            out.append(int(frames[i]))
            last = i
    return out


methods = {
    "content27": cuts_from(content, 27.0),             # PySceneDetect default
    "content20": cuts_from(content, 20.0),             # Test 1's suggested fix
    "content15": cuts_from(content, 15.0),
    # AdaptiveDetector default: ratio >= 3.0 AND content_val >= 15
    "adaptive3": cuts_from(adaptive, 3.0, extra=np.nan_to_num(content) >= 15.0),
}


def write_cuts(name, cuts):
    bounds = [int(frames[0])] + cuts + [int(frames[-1]) + 1]
    with open(d / f"cuts_{name}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["shot", "start_frame", "end_frame", "frames", "start_s", "end_s"])
        for k in range(len(bounds) - 1):
            s, e = bounds[k], bounds[k + 1] - 1
            w.writerow([k + 1, s, e, e - s + 1, f"{s/FPS:.3f}", f"{(e+1)/FPS:.3f}"])
    return np.diff(bounds)


# Candidate dissolves: elevated-but-sub-threshold runs
elev = np.nan_to_num(content) >= DISS_LEVEL
dissolves, i = [], 0
while i < N:
    if elev[i]:
        j = i
        while j < N and elev[j]:
            j += 1
        seg = content[i:j]
        if j - i >= DISS_MIN_RUN and np.nanmax(seg) < 27.0:
            dissolves.append((int(frames[i]), int(frames[j - 1]), j - i, float(np.nanmean(seg)), float(np.nanmax(seg))))
        i = j
    else:
        i += 1
with open(d / "dissolves.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["start_frame", "end_frame", "frames", "mean_content", "max_content", "start_s"])
    for s, e, n, mu, mx in dissolves:
        w.writerow([s, e, n, f"{mu:.1f}", f"{mx:.1f}", f"{s/FPS:.2f}"])

summary = []
lens = {}
for name, cuts in methods.items():
    L = write_cuts(name, cuts)
    lens[name] = L
    summary.append(f"{name:10s}: {len(cuts)+1:5d} shots | median {np.median(L)/FPS:5.2f}s | "
                   f"mean {np.mean(L)/FPS:5.2f}s | <1s {np.mean(L < FPS)*100:4.1f}% | longest {L.max()/FPS:6.1f}s")
summary.append(f"candidate dissolves (>= {DISS_MIN_RUN} frames with content_val >= {DISS_LEVEL}, max < 27): {len(dissolves)}")
# agreement between methods (cut within +-2 frames)
def match(a, b, tol=2):
    b = np.array(b)
    return sum(np.any(np.abs(b - x) <= tol) for x in a)
names = list(methods)
for x in names:
    for y in names:
        if x < y:
            summary.append(f"agree {x} vs {y}: {match(methods[x], methods[y])}/{len(methods[x])} of {x} found in {y}; "
                           f"{match(methods[y], methods[x])}/{len(methods[y])} of {y} found in {x}")
open(d / "pass2_summary.txt", "w").write("\n".join(summary) + "\n")
print("\n".join(summary))

# ---- plots -----------------------------------------------------------------
t = frames / FPS / 60
fig, ax = plt.subplots(figsize=(14, 3.6))
ax.plot(t, content, lw=0.3, color="#355c7d")
for thr, c in ((27, "#c0392b"), (20, "#e67e22"), (15, "#27ae60")):
    ax.axhline(thr, color=c, lw=0.8, ls="--", label=f"threshold {thr}")
ax.set_xlim(0, t[-1]); ax.set_ylim(0, min(np.nanmax(content), 120))
ax.set_xlabel("film time (min)"); ax.set_ylabel("content_val")
ax.set_title("Frame-to-frame content change across the whole film")
ax.legend(loc="upper right", fontsize=8)
fig.tight_layout(); fig.savefig(img / "01_content_val_full.png", dpi=110); plt.close(fig)

fig, ax = plt.subplots(figsize=(10, 3.6))
bins = np.logspace(np.log10(MIN_LEN / FPS), np.log10(max(L.max() for L in lens.values()) / FPS), 40)
for name, c in (("content27", "#c0392b"), ("content20", "#e67e22"), ("adaptive3", "#2c3e50")):
    ax.hist(lens[name] / FPS, bins=bins, histtype="step", lw=1.4, color=c, label=f"{name} ({len(lens[name])} shots)")
ax.set_xscale("log"); ax.set_xlabel("shot length (s, log)"); ax.set_ylabel("shots")
ax.set_title("Shot-length distribution by detection method"); ax.legend(fontsize=8)
fig.tight_layout(); fig.savefig(img / "01_shot_length_hist.png", dpi=110); plt.close(fig)
print("plots written")
