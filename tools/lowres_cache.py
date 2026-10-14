#!/usr/bin/env python3
"""
One decode of the whole film (tools/frameio.py, span-aware) into a low-res
grey cache indexed by film frame index, so frame-to-frame analysis (cut
verification, dissolve detection) never needs to decode again.

Writes:
  shots/lowres_gray64x36.npy   uint8 [N, 36, 64]  (N = last film index + 1)
  shots/lowres_valid.npy       bool  [N]          False = no picture (damaged span / missing)
  shots/opencv_diff.npy        float32 [N]        mean |frame i - previous valid frame| (NaN if invalid)
                               (name kept for tools/check_alignment*.py)

Usage: python tools/lowres_cache.py <video>
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from frameio import iter_frames  # noqa: E402

N = 116734 + 64          # header frame count + margin; trimmed at the end
W, H = 64, 36
cache = np.zeros((N, H, W), np.uint8)
valid = np.zeros(N, bool)
t0, n, last = time.time(), 0, 0
for idx, fr in iter_frames(sys.argv[1], width=W, gray=True):
    cache[idx] = fr
    valid[idx] = True
    last = max(last, idx)
    n += 1
    if n % 12000 == 0:
        print(f"{n} frames (film idx {idx}), {n/(time.time()-t0):.0f} fps", flush=True)
cache, valid = cache[:last + 1], valid[:last + 1]

diff = np.full(last + 1, np.nan, np.float32)
prev = None
for i in range(last + 1):
    if not valid[i]:
        continue
    f = cache[i].astype(np.float32)
    if prev is not None:
        diff[i] = np.abs(f - prev).mean()
    prev = f

out = Path("shots")
np.save(out / "lowres_gray64x36.npy", cache)
np.save(out / "lowres_valid.npy", valid)
np.save(out / "opencv_diff.npy", diff)
print(f"DONE {n} frames, film indices 0..{last}, {int((~valid).sum())} indices without picture, "
      f"{(time.time()-t0)/60:.1f} min", flush=True)
