#!/usr/bin/env python3
"""
Chunked SAM2 run of a long segment through ComfyUI (docs/X01).

Chunks of CHUNK frames overlap by 1 frame. Chunk 1 uses hand-picked prompts;
chunk k>1 is prompted automatically from chunk k-1's CLEANED mask at the shared frame:
  positives  distance-transform maxima inside the cleaned mask, one per band along
             its longer axis (>= MIN_DEPTH px deep, >= EDGE px from frame edge);
             every positive is checked to sit on a hair-dark pixel (V < DARK_V)
  negatives  the deepest points of whatever the raw mask leaked onto (raw minus
             cleaned), then points in a ring 15-40 px outside the cleaned mask on
             pixels that are NOT dark (V > 40), spread by farthest-point sampling

Cleaning (docs/X01 step 3): hair in this shot is near-black, the forest it drifts
onto is V 50-90. Cleaned mask = raw mask restricted to within SUPPORT_R px of its
own dark pixels (dark components >= 2% of the largest, after closing the highlight
lines that split the hair). This keeps the thin blue
highlight lines inside the hair and drops solid patches of forest.

ComfyUI only produces raw masks (its composite step held every 1080p frame in RAM
and is where the first run crashed); composites are made here from cleaned masks.

Usage: python tools/run_long_shot.py seg0703 --chunk 140 [--from-chunk K] [--to-chunk K]
--from-chunk K resumes: chunks < K are taken as already done, and chunk K is prompted
from the mask already on disk at its first frame. --to-chunk K stops after chunk K
(for a seam check) without building the videos.
Writes masks/<seg>_sam2_raw/, masks/<seg>_sam2/ (cleaned), out/<seg>_comp_{white,black}_sam2/,
       out/<seg>_sam2[_black].mp4, checks/seam_<seg>_c<k>.jpg,
       shots/<seg>_chunks.json (prompts, timings and purity per chunk)
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import sam2_workflow as wf  # noqa: E402

OUT = Path(r"C:/Users/POTHEN/AppData/Local/Comfy-Desktop/ComfyUI-Shared/output/qe")
FFMPEG = r"C:/Users/POTHEN/AppData/Local/autolumelive_colab/ffmpeg.exe"
FILM_FPS = 24000 / 1001
EDGE, MIN_DEPTH = 20, 6
DARK_V, SUPPORT_R = 25, 6
MIN_SEED_PX = 5000      # cleaned seed smaller than this = hair lost, stop

MANUAL = {  # chunk-1 prompts, picked on f_0001 (docs/X01 step 2)
    "seg0703": ([(1660, 21), (1853, 318), (1899, 413), (1899, 480)],
                [(1400, 60), (1650, 350), (1000, 300), (1400, 450), (150, 700),
                 # forest wedge between hair and the top-right corner (step 3):
                 # the first run's f_0001 mask covered it, and it seeded the drift
                 (1800, 40), (1845, 120)]),
}
# Hand-picked corrective prompts, {seg: {chunk: [(segment frame number, pos, neg)]}}.
# seg0703 c4: SAM2 drops the pure-black hair at the bottom frame edge in f_0418-0436
# and f_0468-0490 (docs/X01 step 4); positives on that hair, negatives on her skin/dress.
# Without the forest negatives the f_0487 correction flooded that frame onto the forest.
CORRECTIONS = {
    "seg0703": {4: [(425, [(1860, 1010), (1700, 1045)], [(1400, 1040), (1300, 1000)]),
                    (487, [(1790, 1010), (1605, 1011)], [(1400, 1040), (1300, 1000),
                          (1700, 120), (1880, 200), (150, 150)])]},
}
FILLS = {"white": 255, "black": 0}


def free_comfy():
    req = urllib.request.Request(f"{wf.COMFY}/free", data=json.dumps(
        {"unload_models": True, "free_memory": True}).encode(),
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req).read()


def disk(r):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def value(frame):
    return cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[..., 2]


def clean_mask(raw, frame):
    """raw: uint8 0-255 (SAM2 mask, already grown+blurred). Returns cleaned uint8 alpha."""
    dark = ((raw > 127) & (value(frame) < DARK_V)).astype(np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    # bridge the thin highlight lines that split the hair into pieces, else a
    # V=0 hair piece cut off by a line is dropped as "small" (f_0418, step 4)
    joined = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, disk(4))
    n, lab, st, _ = cv2.connectedComponentsWithStats(joined, 8)
    if n <= 1:
        return np.zeros_like(raw)
    areas = st[1:, cv2.CC_STAT_AREA]
    keep = np.isin(lab, 1 + np.nonzero(areas >= max(200, 0.02 * areas.max()))[0]) & (dark > 0)
    support = cv2.dilate(keep.astype(np.uint8), disk(SUPPORT_R)).astype(np.float32)
    support = cv2.GaussianBlur(support, (5, 5), 2.0)
    return (raw.astype(np.float32) * support).astype(np.uint8)


def deepest(m, n, vertical=None):
    """Up to n distance-transform maxima of binary m, one per band along its longer axis."""
    dt = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 5)
    dt[:EDGE] = dt[-EDGE:] = 0
    dt[:, :EDGE] = dt[:, -EDGE:] = 0
    ys, xs = np.nonzero(dt)
    if not len(ys):
        return []
    if vertical is None:
        vertical = (ys.max() - ys.min()) >= (xs.max() - xs.min())
    lo, hi = (ys.min(), ys.max()) if vertical else (xs.min(), xs.max())
    out = []
    for b in range(n):
        a0, a1 = lo + (hi - lo) * b // n, lo + (hi - lo) * (b + 1) // n + 1
        band = np.zeros_like(dt)
        if vertical:
            band[a0:a1] = dt[a0:a1]
        else:
            band[:, a0:a1] = dt[:, a0:a1]
        if band.max() >= MIN_DEPTH:
            y, x = np.unravel_index(np.argmax(band), band.shape)
            out.append((int(x), int(y)))
    return out


def derive_prompts(raw, frame):
    v = value(frame)
    clean = clean_mask(raw, frame)
    m = (clean > 127) & (v < DARK_V)          # positives only on hair-dark pixels
    if m.sum() < MIN_SEED_PX:
        raise RuntimeError(f"cleaned seed too small ({int(m.sum())} px): hair lost")
    pos = deepest(m, 4)
    assert all(v[y, x] < DARK_V for x, y in pos), "positive off hair"
    neg = []
    leak = ((raw > 127) & ~cv2.dilate((clean > 127).astype(np.uint8), disk(15)).astype(bool)
            & (v > 40)).astype(np.uint8)
    leak = cv2.morphologyEx(leak, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(leak, 8)
    for j in (1 + np.argsort(-st[1:, cv2.CC_STAT_AREA]))[:2]:
        if st[j, cv2.CC_STAT_AREA] >= 2000:
            neg += deepest(lab == j, 1)
    mb = (clean > 127).astype(np.uint8)
    ring = cv2.dilate(mb, disk(40)) & ~cv2.dilate(mb, disk(15)) & (v > 40).astype(np.uint8)
    ring[:EDGE] = ring[-EDGE:] = 0
    ring[:, :EDGE] = ring[:, -EDGE:] = 0
    ry, rx = np.nonzero(ring)
    if len(rx):
        cand = np.stack([rx, ry], 1)[:: max(1, len(rx) // 4000)]
        sel = [cand[len(cand) // 2]]
        while len(sel) < 4:
            d = np.min([np.hypot(*(cand - s).T) for s in sel], axis=0)
            sel.append(cand[int(np.argmax(d))])
        neg += [(int(x), int(y)) for x, y in sel]
    return pos, neg, clean


def overlay(frame, raw, clean, pos=(), neg=(), label=""):
    o = frame.copy()
    o[(raw > 127) & ~(clean > 127)] = (0, 255, 255)   # yellow: dropped by cleaning
    o[clean > 127] = (0, 0, 255)                      # red: kept
    for p in pos:
        cv2.circle(o, p, 16, (0, 255, 0), -1)
    for p in neg:
        cv2.circle(o, p, 16, (255, 0, 255), -1)
    o = cv2.resize(o, (640, 360))
    cv2.putText(o, label, (10, 30), 0, 0.7, (255, 255, 255), 2)
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seg")
    ap.add_argument("--chunk", type=int, default=140)
    ap.add_argument("--from-chunk", type=int, default=1)
    ap.add_argument("--to-chunk", type=int, default=0)
    a = ap.parse_args()
    seg = a.seg
    src = ROOT / "frames" / seg
    n = len(list(src.glob("f_*.png")))
    starts = list(range(0, n - 1, a.chunk - 1))
    chunks = [(s, min(s + a.chunk, n)) for s in starts]          # [start, end) local 0-based
    print(f"{seg}: {n} frames -> chunks {chunks}", flush=True)

    dst = {"raw": ROOT / "masks" / f"{seg}_sam2_raw",
           "mask": ROOT / "masks" / f"{seg}_sam2",
           "white": ROOT / "out" / f"{seg}_comp_white_sam2",
           "black": ROOT / "out" / f"{seg}_comp_black_sam2"}
    if a.from_chunk == 1:                     # fresh run: no stale frames from older runs
        for d in dst.values():
            shutil.rmtree(d, ignore_errors=True)
    for d in dst.values():
        d.mkdir(parents=True, exist_ok=True)
    log_path = ROOT / "shots" / f"{seg}_chunks.json"
    log = json.load(open(log_path)) if a.from_chunk > 1 and log_path.exists() else []
    log = [r for r in log if r["chunk"] < a.from_chunk]
    pos, neg = MANUAL[seg]
    last = a.to_chunk or len(chunks)
    for k, (s, e) in enumerate(chunks, 1):
        if k < a.from_chunk or k > last:
            continue
        tag = f"c{k}"
        shutil.rmtree(OUT / f"{seg}_{tag}", ignore_errors=True)
        seed_img = None
        if k > 1:
            raw = cv2.imread(str(dst["raw"] / f"f_{s + 1:04d}.png"), cv2.IMREAD_GRAYSCALE)
            frame = cv2.imread(str(src / f"f_{s + 1:04d}.png"))
            pos, neg, clean = derive_prompts(raw, frame)
            seed_img = overlay(frame, raw, clean, pos, neg, f"seed f_{s + 1:04d} (end of c{k - 1})")
        fixes = [(f - s - 1, p, q) for f, p, q in CORRECTIONS.get(seg, {}).get(k, [])]
        print(f"chunk {k}: frames f_{s+1:04d}-f_{e:04d} ({e-s}), pos {pos}, neg {neg}"
              + (f", corrections at local {[f for f, _, _ in fixes]}" if fixes else ""), flush=True)
        free_comfy()
        g = wf.build(seg, cap=e - s, fills=(), tag=tag, skip=s,
                     prompts=[(0, pos, neg)] + fixes, fps=FILM_FPS)
        json.dump(g, open(ROOT / "workflows" / f"{seg}_{tag}.json", "w"), indent=1)
        t0 = time.time()
        wf.submit(g)
        dt = time.time() - t0
        files = sorted((OUT / f"{seg}_{tag}").glob("*_.png"))
        if len(files) != e - s:
            sys.exit(f"chunk {k}: expected {e - s} masks, got {len(files)}")
        kept = []
        for i, fpath in enumerate(files):
            name = f"f_{s + i + 1:04d}.png"
            raw = cv2.imread(str(fpath), cv2.IMREAD_GRAYSCALE)
            frame = cv2.imread(str(src / name))
            clean = clean_mask(raw, frame)
            kept.append(float((clean > 127).sum()) / max(1, int((raw > 127).sum())))
            cv2.imwrite(str(dst["raw"] / name), raw)
            cv2.imwrite(str(dst["mask"] / name), clean)
            al = (clean.astype(np.float32) / 255)[..., None]
            for fill, val in FILLS.items():
                cv2.imwrite(str(dst[fill] / name), (frame * al + val * (1 - al)).astype(np.uint8))
        endf = cv2.imread(str(src / f"f_{e:04d}.png"))
        end_img = overlay(endf, cv2.imread(str(dst["raw"] / f"f_{e:04d}.png"), 0),
                          cv2.imread(str(dst["mask"] / f"f_{e:04d}.png"), 0), label=f"end f_{e:04d} (c{k})")
        mid = (s + e) // 2 + 1
        mid_img = overlay(cv2.imread(str(src / f"f_{mid:04d}.png")),
                          cv2.imread(str(dst["raw"] / f"f_{mid:04d}.png"), 0),
                          cv2.imread(str(dst["mask"] / f"f_{mid:04d}.png"), 0), label=f"mid f_{mid:04d} (c{k})")
        row = [x for x in (seed_img, mid_img, end_img) if x is not None]
        cv2.imwrite(str(ROOT / "checks" / f"seam_{seg}_c{k}.jpg"), np.hstack(row), [cv2.IMWRITE_JPEG_QUALITY, 85])
        kept = np.array(kept)
        rec = {"chunk": k, "local_frames": [s + 1, e], "pos": pos, "neg": neg,
               "corrections": CORRECTIONS.get(seg, {}).get(k, []), "seconds": round(dt),
               "masks": len(files), "kept_frac_min": round(float(kept.min()), 3),
               "kept_frac_median": round(float(np.median(kept)), 3),
               "kept_frac_end": round(float(kept[-1]), 3),
               "frames_kept_below_50pct": [s + 1 + int(i) for i in np.nonzero(kept < 0.5)[0]]}
        log.append(rec)
        json.dump(log, open(log_path, "w"), indent=1)   # after every chunk, so a crash keeps it
        print(f"chunk {k}: {len(files)} masks in {dt:.0f}s; cleaned/raw min {rec['kept_frac_min']} "
              f"median {rec['kept_frac_median']} end {rec['kept_frac_end']}; "
              f"{len(rec['frames_kept_below_50pct'])} frames < 50%", flush=True)

    if last < len(chunks):
        print(f"STOPPED after chunk {last} for seam check", flush=True)
        return
    for fill, suffix in (("white", ""), ("black", "_black")):
        subprocess.run([FFMPEG, "-v", "error", "-y", "-framerate", "24000/1001",
                        "-i", str(dst[fill] / "f_%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-crf", "18", str(ROOT / "out" / f"{seg}_sam2{suffix}.mp4")], check=True)
    print("DONE", seg, flush=True)


if __name__ == "__main__":
    main()
