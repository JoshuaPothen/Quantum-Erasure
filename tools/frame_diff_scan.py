#!/usr/bin/env python3
"""
Independent per-frame change signal, indexed by film frame index
(ffmpeg pts via tools/frameio.py).

diff[i] = mean |frame i - previous decoded frame| on 160x90 grey thumbnails;
NaN where film index i has no picture (damaged span) or is the first frame.

Usage: python tools/frame_diff_scan.py <video> shots/opencv_diff.npy
(the output name is historical; the signal now comes from ffmpeg)
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from frameio import iter_frames  # noqa: E402

vals, prev, t0, n = {}, None, time.time(), 0
for idx, fr in iter_frames(sys.argv[1], width=160, gray=True):
    n += 1
    f = fr.astype(np.float32)
    if prev is not None:
        vals[idx] = float(np.abs(f - prev).mean())
    prev = f
    if n % 12000 == 0:
        print(f"{n} frames, {n/(time.time()-t0):.0f} fps", flush=True)
arr = np.full(max(vals) + 1, np.nan, np.float32)
for k, v in vals.items():
    arr[k] = v
np.save(sys.argv[2], arr)
print(f"DONE {n} frames decoded, film indices 0..{len(arr)-1}, in {(time.time()-t0)/60:.1f} min", flush=True)
