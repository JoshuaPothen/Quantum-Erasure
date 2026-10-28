#!/usr/bin/env python3
"""
"Her cut": only the segments Pocahontas is in, back to back, no audio (film/README step 21).
A separate output from tools/assemble_film.py; the full film is untouched.

1. picks every segment whose qc.json status isn't "absent" (credits are skipped), in film order
2. checks each segNNNN.mp4 has exactly `frames` frames
3. concat demuxer, stream copy, audio dropped -> film/her_cut/Pocahontas_her_cut.mp4
4. film/her_cut/index.csv: where each segment sits in the cut and in the film

Usage: python tools/assemble_her_cut.py
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from assemble_film import nframes, SEGS  # noqa: E402
import run_long_shot as rl  # noqa: E402

OUT = ROOT / "film" / "her_cut"
FPS = 24000 / 1001


def tc(frame):
    s = frame / FPS
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:06.3f}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [r for r in csv.DictReader(open(ROOT / "shots" / "shots_v1.csv")) if r["kind"] != "credits"]
    parts, bad, at = [], [], 0
    for r in rows:
        k = int(r["seg"])
        d = SEGS / f"seg{k:04d}"
        q = json.load(open(d / "qc.json"))
        if q["status"] == "absent":
            continue
        mp4, n = d / f"seg{k:04d}.mp4", int(r["frames"])
        if nframes(mp4) != n:
            bad.append(k)
        parts.append({"seg": k, "status": q["status"], "frames": n,
                      "cut_start": tc(at), "film_start": tc(int(r["start_frame"])),
                      "film_frames": f"{r['start_frame']}-{r['end_frame']}", "mp4": mp4})
        at += n
    if bad:
        sys.exit(f"{len(bad)} segments missing or wrong length: {bad[:20]}")
    print(f"{len(parts)} segments with her, {at} frames ({tc(at)})")
    lst = OUT / "concat.txt"
    lst.write_text("".join(f"file '{p['mp4'].as_posix()}'\n" for p in parts))
    out = OUT / "Pocahontas_her_cut.mp4"
    subprocess.run([rl.FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-map", "0:v:0", "-c", "copy", "-an", "-movflags", "+faststart", str(out)], check=True)
    got = nframes(out)
    print(f"cut: {got} frames, expected {at}")
    if got != at:
        sys.exit("frame count mismatch after concat")
    with open(OUT / "index.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["seg", "status", "frames", "cut_start", "film_start", "film_frames"])
        w.writeheader()
        w.writerows({k: v for k, v in p.items() if k != "mp4"} for p in parts)
    print("wrote", out)


if __name__ == "__main__":
    main()
