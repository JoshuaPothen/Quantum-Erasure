#!/usr/bin/env python3
"""
Frame-exact thumbnail grab: one decode through tools/frameio.py (ffmpeg pts =
film frame index, same numbering as shots/cuts_*.csv), saving only the
requested film indices.

Usage: python tools/grab_frames.py <video> <frames.txt> <out_dir> [--width 320]
frames.txt: one film frame index per line.  Writes <out_dir>/f<index:06d>.jpg
Indices with no picture in the source (damaged spans) are reported, not faked.
"""
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
from frameio import iter_frames  # noqa: E402

video, lst, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
W = int(sys.argv[sys.argv.index("--width") + 1]) if "--width" in sys.argv else 320
out.mkdir(parents=True, exist_ok=True)
want = sorted({int(x) for x in open(lst).read().split()})
todo = {f for f in want if not (out / f"f{f:06d}.jpg").exists()}
print(f"{len(want)} requested, {len(todo)} not yet on disk", flush=True)
if not todo:
    sys.exit(0)
last = max(todo)

t0, saved, n = time.time(), 0, 0
for idx, fr in iter_frames(video, width=W):
    n += 1
    if idx in todo:
        cv2.imwrite(str(out / f"f{idx:06d}.jpg"), fr, [cv2.IMWRITE_JPEG_QUALITY, 88])
        saved += 1
    if idx >= last:
        break
    if n % 12000 == 0:
        print(f"film frame {idx} ({100*idx/last:.0f}%) {n/(time.time()-t0):.0f} fps, {saved} saved", flush=True)
missing = sorted(f for f in todo if not (out / f"f{f:06d}.jpg").exists())
print(f"DONE decoded {n} frames, saved {saved} in {(time.time()-t0)/60:.1f} min; "
      f"{len(missing)} requested indices have no picture: {missing[:40]}", flush=True)
