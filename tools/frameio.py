"""
Canonical frame reading for the project (docs/01_shot_detection.md, step 6).

Frame identity comes from ffmpeg's own presentation timestamps:
  film_idx = round(pts_seconds * 24000/1001), 0-based
Frames are decoded by an ffmpeg pipe (rawvideo on stdout) while `showinfo`
reports each frame's pts on stderr; -copyts keeps pts absolute when seeking.

Damaged spans (shots/damaged_spans.csv) are never decoded through: decoding
continuously across the corrupted GOP at 6:58.7 makes the h264 decoder pair
every later picture with the wrong pts (+1 frame, persistent). iter_frames
stops before each span and restarts a fresh decoder at the span's resume
keyframe. Frames inside a span are not yielded at all.

Why not OpenCV: on this file OpenCV's frame counter runs 31 low after the
damage and its CAP_PROP_POS_MSEC runs 1 frame high (same decoder effect).
PySceneDetect's stats / cut lists match fresh-decoder ffmpeg pts (verified).
"""
import csv
import re
import subprocess
import threading
from pathlib import Path

import numpy as np

FFMPEG = r"C:/Users/POTHEN/AppData/Local/autolumelive_colab/ffmpeg.exe"
FPS = 24000 / 1001
SRC_W, SRC_H = 1920, 1080
SPANS_CSV = Path(__file__).resolve().parent.parent / "shots" / "damaged_spans.csv"
_NPTS = re.compile(rb"n:\s*(\d+)\s+pts:\s*-?\d+\s+pts_time:\s*(-?[0-9.]+)")


def load_damaged_spans(path=SPANS_CSV):
    """[(start_frame, end_frame, resume_frame, resume_s)], sorted."""
    if not Path(path).exists():
        return []
    rows = csv.DictReader(open(path, newline=""))
    return sorted((int(r["start_frame"]), int(r["end_frame"]), int(r["resume_frame"]),
                   float(r["resume_s"])) for r in rows)


def _segment(video, w, h, gray, start_s, stop_idx, end_idx):
    """One ffmpeg decode from start_s; yields (idx, frame) with idx < stop_idx
    (if given) and idx <= end_idx (if given)."""
    ch = 1 if gray else 3
    cmd = [FFMPEG, "-v", "info", "-nostats", "-copyts"]
    if start_s is not None:
        cmd += ["-ss", f"{max(start_s, 0):.3f}"]
    cmd += ["-i", video, "-map", "0:v:0"]
    # No -t/-to: with -copyts ffmpeg compares them against absolute timestamps
    # (-t 4 from a 12 s seek wrote nothing). Window ends are enforced here.
    vf = (f"scale={w}:{h}:flags=area," if w != SRC_W else "") + "showinfo"
    # -fps_mode passthrough: emit exactly the decoded frames. The default (CFR
    # for rawvideo) filled the 1.3 s hole at 6:58.7 with 32 duplicate frames
    # that have no showinfo line -- and would fake picture in any extraction.
    cmd += ["-vf", vf, "-fps_mode", "passthrough",
            "-f", "rawvideo", "-pix_fmt", "gray" if gray else "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # default bufsize: bufsize=10**8 made reads 13x slower (docs/03)

    # showinfo's "n: <k> pts: <p> pts_time: <t>" keyed by its frame counter k.
    # h264 error messages can be spliced into showinfo lines, so match the
    # fragment anywhere in the byte stream, not per line.
    pts, cond, done, maxn = {}, threading.Condition(), [False], [-1]

    def read_err():
        buf = b""
        while True:
            chunk = p.stderr.read1(65536) if hasattr(p.stderr, "read1") else p.stderr.read(65536)
            if not chunk:
                break
            buf += chunk
            last_end = 0
            for m in _NPTS.finditer(buf):
                with cond:
                    k_, t_ = int(m.group(1)), float(m.group(2))
                    pts[k_] = t_
                    maxn[0] = max(maxn[0], k_)
                    cond.notify_all()
                last_end = m.end()
            buf = buf[last_end:] if last_end else buf[-4096:]
        with cond:
            done[0] = True
            cond.notify_all()

    threading.Thread(target=read_err, daemon=True).start()
    size, k, prev = w * h * ch, 0, -1
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            with cond:
                # wait for this frame's pts, or a later frame's (then this
                # one's line was garbled), or ffmpeg finishing
                while k not in pts and maxn[0] <= k and not done[0]:
                    cond.wait()
                t = pts.pop(k, None)
            k += 1
            if t is None:
                idx = prev + 1
                print(f"frameio WARNING: no readable pts for decoded frame #{k-1}; numbered {idx}",
                      flush=True)
            else:
                idx = round(t * FPS)
            if idx <= prev:              # never emit an index twice
                idx = prev + 1
            prev = idx
            if (stop_idx is not None and idx >= stop_idx) or (end_idx is not None and idx > end_idx):
                break
            fr = np.frombuffer(buf, np.uint8).reshape(h, w) if gray else \
                np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            yield idx, fr
    finally:
        p.stdout.close()
        p.kill()
        p.wait()


def iter_frames(video, width=None, start_s=None, end_s=None, gray=False, spans=None):
    """Yield (film_idx, frame) for every decodable frame in order, skipping
    damaged spans and restarting the decoder after each.

    width: output width (height keeps 16:9); None = full 1920x1080.
    start_s / end_s: optional time window in seconds.
    gray: single-channel uint8 output instead of BGR.
    spans: damaged spans; default = shots/damaged_spans.csv.
    """
    w = width or SRC_W
    h = round(w * SRC_H / SRC_W)
    spans = load_damaged_spans() if spans is None else spans
    start_idx = 0 if start_s is None else round(start_s * FPS)
    end_idx = None if end_s is None else round(end_s * FPS)

    cur_s, cur_idx = start_s, start_idx
    for s0, s1, resume_idx, resume_s in spans:
        if s1 < cur_idx:
            continue                         # span already behind us
        if end_idx is not None and s0 > end_idx:
            break                            # span after the window
        if cur_idx < s0:                     # decode up to the span
            yield from _segment(video, w, h, gray, cur_s, s0, end_idx)
        cur_s, cur_idx = resume_s, resume_idx  # fresh decoder after the span
    if end_idx is None or cur_idx <= end_idx:
        yield from _segment(video, w, h, gray, cur_s, None, end_idx)
