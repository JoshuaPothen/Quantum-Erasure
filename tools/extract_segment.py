#!/usr/bin/env python3
"""
Extract one segment of shots/shots_v1.csv to full-resolution PNGs through
tools/frameio.py (ffmpeg pts = film frame index; damaged-span aware).

Usage: python tools/extract_segment.py <video> <seg> [--out frames]
Writes:
  <out>/seg<seg:04d>/f_%04d.png     1-based within the segment (Test 1 convention)
  <out>/seg<seg:04d>/frame_map.csv  local f_XXXX -> film frame index
Fails loudly if the segment has a gap (film index with no picture).
"""
import csv
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
from frameio import iter_frames, FPS  # noqa: E402

video, seg = sys.argv[1], int(sys.argv[2])
root = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else Path("frames")
row = next(r for r in csv.DictReader(open("shots/shots_v1.csv")) if int(r["seg"]) == seg)
s, e = int(row["start_frame"]), int(row["end_frame"])
out = root / f"seg{seg:04d}"
out.mkdir(parents=True, exist_ok=True)

got = []
for idx, fr in iter_frames(video, start_s=s / FPS - 1.0, end_s=e / FPS + 0.01):
    if s <= idx <= e:
        k = len(got) + 1
        cv2.imwrite(str(out / f"f_{k:04d}.png"), fr)
        got.append((k, idx))
with open(out / "frame_map.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["local", "film_idx"])
    w.writerows(got)
missing = sorted(set(range(s, e + 1)) - {i for _, i in got})
print(f"seg {seg} ({row['kind']}) film {s}-{e}: wrote {len(got)} frames to {out}; "
      f"{len(missing)} missing indices {missing[:10]}")
if missing:
    sys.exit("segment has gaps - see docs/01 step 6 before using it")
