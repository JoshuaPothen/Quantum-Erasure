#!/usr/bin/env python3
"""
Combine the per-segment outputs into the final film (film/README step 9).

1. checks every segment of shots/shots_v1.csv has film/segments/segNNNN/segNNNN.mp4 with exactly
   `frames` frames (a missing/short segment stops the assembly - it would shift the audio)
2. the credits (kept as-is, user decision 2026-10-21) are re-encoded from the source through
   tools/frameio.py with the same x264 settings as the segments -> film/final/credits.mp4
3. concat demuxer, stream copy -> film/final/_video.mp4
4. mux the BDrip's English AC3 5.1 track (stream 0:1, starts at 0 = film frame 0), copied
   -> film/final/Pocahontas_hair_only.mp4

Usage: python tools/assemble_film.py [--check-only]
"""
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from frameio import iter_frames, FPS  # noqa: E402
import run_long_shot as rl  # noqa: E402

VIDEO = str(ROOT / "Pocahontas (1995) BDrip 1080p ENG-ITA MultiSub x264 blyuray -Shiv@.mkv")
SEGS = ROOT / "film" / "segments"
FIN = ROOT / "film" / "final"
X264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-g", "48"]


def nframes(mp4):
    """Exact decoded frame count (ffmpeg -f null; container metadata isn't trusted).
    Decodes: with -c copy this ffmpeg reports no frame= line (README step 20)."""
    r = subprocess.run([rl.FFMPEG, "-v", "error", "-i", str(mp4), "-map", "0:v:0",
                        "-f", "null", "-progress", "pipe:1", "-nostats", "-"], capture_output=True, text=True)
    vals = [ln.split("=")[1] for ln in r.stdout.splitlines() if ln.startswith("frame=")]
    return int(vals[-1]) if vals else -1


def credits(row, dst):
    s, e = int(row["start_frame"]), int(row["end_frame"])
    p = subprocess.Popen([rl.FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "1920x1080",
                          "-framerate", "24000/1001", "-i", "-"] + X264 + [str(dst)], stdin=subprocess.PIPE)
    n = 0
    for idx, fr in iter_frames(VIDEO, start_s=s / FPS - 1.0, end_s=e / FPS + 0.01):
        if s <= idx <= e:
            p.stdin.write(fr.tobytes())
            n += 1
    p.stdin.close()
    p.wait()
    if n != e - s + 1:
        sys.exit(f"credits: got {n} frames, expected {e - s + 1}")


def main():
    FIN.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(ROOT / "shots" / "shots_v1.csv")))
    parts, bad = [], []
    for r in rows:
        k = int(r["seg"])
        mp4 = FIN / "credits.mp4" if r["kind"] == "credits" else SEGS / f"seg{k:04d}" / f"seg{k:04d}.mp4"
        if r["kind"] != "credits":
            n = nframes(mp4) if mp4.exists() else -1
            if n != int(r["frames"]):
                bad.append((k, n, int(r["frames"])))
        parts.append((r, mp4))
    if bad:
        print(f"{len(bad)} segments missing or wrong length (seg, got, want): {bad[:20]}")
        sys.exit(1)
    print(f"all {len(rows) - 1} segment videos present with the right frame counts")
    if "--check-only" in sys.argv:
        return
    cr = next(r for r, _ in parts if r["kind"] == "credits")
    if not (FIN / "credits.mp4").exists() or nframes(FIN / "credits.mp4") != int(cr["frames"]):
        credits(cr, FIN / "credits.mp4")
    lst = FIN / "concat.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for _, p in parts))
    subprocess.run([rl.FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(FIN / "_video.mp4")], check=True)
    total = sum(int(r["frames"]) for r in rows)
    got = nframes(FIN / "_video.mp4")
    print(f"video: {got} frames, expected {total}")
    if got != total:
        sys.exit("frame count mismatch after concat")
    out = FIN / "Pocahontas_hair_only.mp4"
    subprocess.run([rl.FFMPEG, "-v", "error", "-y", "-i", str(FIN / "_video.mp4"), "-i", VIDEO,
                    "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-metadata:s:a:0", "language=eng",
                    "-movflags", "+faststart", str(out)], check=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
