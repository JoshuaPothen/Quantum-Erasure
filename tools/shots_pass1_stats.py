#!/usr/bin/env python3
"""
Shot detection, pass 1: decode the film ONCE and save every per-frame metric.

Runs ContentDetector and AdaptiveDetector together with a StatsManager, so the
CSV holds content_val / delta_hue / delta_sat / delta_lum / adaptive_ratio for
every frame. All threshold tuning afterwards (pass 2) reads this CSV instead of
re-decoding 116k frames.

Usage: python tools/shots_pass1_stats.py <video> <out_dir>
Writes: <out_dir>/stats.csv, <out_dir>/scenes_default.csv, <out_dir>/pass1.log
"""
import sys
import time
from pathlib import Path

from scenedetect import open_video, SceneManager, StatsManager
from scenedetect.detectors import ContentDetector, AdaptiveDetector

video_path, out_dir = sys.argv[1], Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)

video = open_video(video_path, backend="opencv")
stats = StatsManager()
sm = SceneManager(stats_manager=stats)
# Defaults on purpose: pass 1 only has to *record* metrics. min_scene_len=1 so
# no cut is suppressed at this stage; pass 2 applies the real filtering.
sm.add_detector(ContentDetector(threshold=27.0, min_scene_len=1))
sm.add_detector(AdaptiveDetector(min_scene_len=1))
sm.auto_downscale = True  # ~256px wide; cut metrics don't need 1080p

total = video.duration.get_frames()
t0 = time.time()
log = open(out_dir / "pass1.log", "w")


def progress(frame_img, position):
    # scenedetect 0.7 passes a FrameTimecode here, not an int
    frame_num = position.get_frames() if hasattr(position, "get_frames") else int(position)
    if frame_num % 2400 == 0:  # every ~100s of film
        el = time.time() - t0
        fps = frame_num / el if el else 0
        msg = f"frame {frame_num}/{total} ({100*frame_num/total:.1f}%) {fps:.0f} fps, eta {((total-frame_num)/fps/60 if fps else 0):.1f} min"
        print(msg, flush=True)
        log.write(msg + "\n"); log.flush()


sm.detect_scenes(video, callback=progress, show_progress=False)
stats.save_to_csv(str(out_dir / "stats.csv"))

scenes = sm.get_scene_list()
with open(out_dir / "scenes_default.csv", "w") as f:
    f.write("shot,start_frame,end_frame,start_tc,end_tc,frames\n")
    for i, (s, e) in enumerate(scenes, 1):
        f.write(f"{i},{s.get_frames()},{e.get_frames()-1},{s.get_timecode()},{e.get_timecode()},{e.get_frames()-s.get_frames()}\n")

msg = f"DONE {total} frames in {(time.time()-t0)/60:.1f} min, {len(scenes)} shots (default, combined detectors)"
print(msg, flush=True)
log.write(msg + "\n")
