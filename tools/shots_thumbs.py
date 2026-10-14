#!/usr/bin/env python3
"""
One decode (tools/frameio.py; ffmpeg pts = film frame index) that saves, for
every shot in a cut list, thumbnails of its first, middle and last frame.

Usage: python tools/shots_thumbs.py <video> shots/cuts_<method>.csv shots/thumbs_<method> [--width 320]
Writes: <out>/s<shot:04d>_{a,m,z}.jpg
If a wanted index has no picture (damaged span), the next decoded frame inside
the same shot is used instead, and the substitution is reported.
"""
import csv
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
from frameio import iter_frames  # noqa: E402

video, cuts_csv, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
W = int(sys.argv[sys.argv.index("--width") + 1]) if "--width" in sys.argv else 320
out.mkdir(parents=True, exist_ok=True)

targets = {}  # film index -> [(shot_end, filename)]
last = 0
for r in csv.DictReader(open(cuts_csv, newline="")):
    k, s, e = int(r["shot"]), int(r["start_frame"]), int(r["end_frame"])
    last = max(last, e)
    for tag, fr in (("a", s), ("m", (s + e) // 2), ("z", e)):
        targets.setdefault(fr, []).append((e, f"s{k:04d}_{tag}.jpg"))
due = sorted(targets)

t0, saved, q = time.time(), 0, 0
carry = []  # (shot_end, filename, wanted_idx) for indices that had no picture
for idx, fr in iter_frames(video, width=W):
    while q < len(due) and due[q] < idx:          # skipped index -> no picture
        carry += [(e, n, due[q]) for e, n in targets[due[q]]]
        q += 1
    names = []
    if q < len(due) and due[q] == idx:
        names = [n for _, n in targets[idx]]
        q += 1
    for e, n, t in carry:
        if idx <= e:
            names.append(n)
            print(f"substituted {n}: film frame {t} has no picture, used {idx}", flush=True)
        else:
            print(f"WARNING {n}: no picture for film frame {t} within its shot", flush=True)
    carry = []
    for name in names:
        cv2.imwrite(str(out / name), fr, [cv2.IMWRITE_JPEG_QUALITY, 88])
        saved += 1
    if idx >= last:
        break
print(f"DONE {saved} thumbs in {(time.time()-t0)/60:.1f} min", flush=True)
