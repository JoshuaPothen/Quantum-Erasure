#!/usr/bin/env python3
"""
SAM3-first hair masking of one segment, with SAM2 as the per-frame fallback (docs/X02).

1. SAM3 (main): CheckpointLoaderSimple(sam3.1) -> CLIPTextEncode(text prompt) ->
   SAM3_Detect on every frame independently -> GrowMask/blur like the SAM2 graph.
   No memory between frames, so an error on one frame can't seed the next.
2. QC every frame:  area >= MIN_PX
                    missed = unmasked hair-dark blobs touching the mask, / area <= MAX_MISSED
                    purity = share of mask pixels with V < QC_V   >= MIN_PURITY
                    area / median(area of the 2 frames each side) in [JUMP_LO, JUMP_HI]
3. SAM2 (fallback): each run of failed frames is re-segmented by SAM2 video
   propagation, seeded from the nearest PASSING SAM3 frame (prompts derived from
   that mask with run_long_shot.derive_prompts, plus one positive per separate
   piece of the mask). The run is propagated forward
   from the last good frame before it, or backward (reversed frame order) from
   the first good frame after it when the run starts the shot. SAM2 frames are
   QC'd the same way; if both fail, the mask with the higher purity - missed is kept.
   A forced frame (SAM3 actually passed) keeps SAM3 unless SAM2 is about as good.

Usage: python tools/run_sam3_shot.py seg0224 --prompt "long black hair:1"
                                     [--force-fallback 50,51,52] [--cap N]
--force-fallback marks frames as failed regardless of QC, to exercise the SAM2 path.
Writes masks/<seg>_sam3/ (final), masks/<seg>_sam3_only/ (SAM3 before fallback),
       out/<seg>_comp_{white,black}_sam3/, out/<seg>_sam3[_black].mp4,
       shots/<seg>_sam3.json (per-frame source, area, purity, flags)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import sam2_workflow as wf  # noqa: E402
import run_long_shot as rl  # noqa: E402

OUT = rl.OUT
SAM3_CKPT = "sam3.1_multiplex_fp16.safetensors"
QC_V, MIN_PURITY, MIN_PX = 40, 0.85, 2000
MAX_MISSED = 0.10   # unmasked near-black (V < rl.DARK_V) blobs > 500 px touching the mask, / mask area
JUMP_LO, JUMP_HI = 0.6, 1.6


def sam3_graph(seg, prompt, threshold, cap):
    g = {}
    nid = iter(range(1, 100))

    def add(cls, **inputs):
        i = str(next(nid))
        g[i] = {"class_type": cls, "inputs": inputs}
        return i
    load = add("VHS_LoadImagesPath", directory=str(ROOT / "frames" / seg),
               image_load_cap=cap, skip_first_images=0, select_every_nth=1)
    ck = add("CheckpointLoaderSimple", ckpt_name=SAM3_CKPT)
    txt = add("CLIPTextEncode", clip=[ck, 1], text=prompt)
    det = add("SAM3_Detect", model=[ck, 0], image=[load, 0], conditioning=[txt, 0],
              threshold=threshold, refine_iterations=2, individual_masks=False)
    grow = add("GrowMask", mask=[det, 0], expand=wf.GROW_PX, tapered_corners=True)
    alpha = add("ImpactGaussianBlurMask", mask=[grow, 0],
                kernel_size=wf.BLUR_KERNEL, sigma=wf.BLUR_SIGMA)
    add("SaveImage", images=[add("MaskToImage", mask=[alpha, 0]), 0],
        filename_prefix=f"qe/{seg}_sam3/mask")
    return g


def stats(mask, frame):
    """(area, purity, missed): purity catches spill onto background, missed catches
    hair left out (the SAM2 fallback passed purity while dropping hair, step 3)."""
    m = mask > 127
    a = int(m.sum())
    v = rl.value(frame)
    if not a:
        return 0, 0.0, 1.0
    d = ((v < rl.DARK_V) & ~m).astype(np.uint8)
    _, lab, st, _ = cv2.connectedComponentsWithStats(d, 8)
    touch = set(np.unique(lab[cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0])) - {0}
    missed = sum(int(st[j, cv2.CC_STAT_AREA]) for j in touch if st[j, cv2.CC_STAT_AREA] > 500) / a
    return a, float(((v < QC_V) & m).sum()) / a, missed


def score(p, ms):
    return p - ms


def seed_prompts(mask, frame):
    """run_long_shot's derived prompts, plus one positive in every separate piece of
    the seed (>= 3% of it) that has none: hair split by an arm is otherwise dropped."""
    pos, neg, clean = rl.derive_prompts(mask, frame)
    m = ((clean > 127) & (rl.value(frame) < rl.DARK_V)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    for j in range(1, n):
        if st[j, cv2.CC_STAT_AREA] >= 0.03 * m.sum() and not any(lab[y, x] == j for x, y in pos):
            pos += rl.deepest(lab == j, 1)
    return pos, neg


def qc(areas, purity, missed, i):
    """Reasons frame i (0-based) fails; empty list = pass."""
    why = []
    if areas[i] < MIN_PX:
        why.append("empty")
    if purity[i] < MIN_PURITY:
        why.append(f"purity {purity[i]:.2f}")
    if missed[i] > MAX_MISSED:
        why.append(f"missed {missed[i]:.2f}")
    nb = [areas[j] for j in range(max(0, i - 2), min(len(areas), i + 3)) if j != i]
    ref = float(np.median(nb)) if nb else 0
    if ref >= MIN_PX and not (JUMP_LO <= areas[i] / ref <= JUMP_HI):
        why.append(f"jump x{areas[i] / ref:.2f}")
    return why


def runs(idx):
    out = []
    for i in sorted(idx):
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seg")
    ap.add_argument("--prompt", default="long black hair:1")
    ap.add_argument("--threshold", type=float, default=0.3)
    ap.add_argument("--force-fallback", default="")
    ap.add_argument("--cap", type=int, default=0)
    a = ap.parse_args()
    seg = a.seg
    src = ROOT / "frames" / seg
    n = len(list(src.glob("f_*.png")))
    n = min(n, a.cap) if a.cap else n
    names = [f"f_{i + 1:04d}.png" for i in range(n)]
    frames = lambda i: cv2.imread(str(src / names[i]))  # noqa: E731
    dst = {"sam3": ROOT / "masks" / f"{seg}_sam3_only", "mask": ROOT / "masks" / f"{seg}_sam3",
           "white": ROOT / "out" / f"{seg}_comp_white_sam3", "black": ROOT / "out" / f"{seg}_comp_black_sam3"}
    for d in dst.values():
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)

    # 1. SAM3
    shutil.rmtree(OUT / f"{seg}_sam3", ignore_errors=True)
    rl.free_comfy()
    g = sam3_graph(seg, a.prompt, a.threshold, a.cap)
    json.dump(g, open(ROOT / "workflows" / f"{seg}_sam3.json", "w"), indent=1)
    t0 = time.time()
    wf.submit(g)
    t_sam3 = time.time() - t0
    files = sorted((OUT / f"{seg}_sam3").glob("*_.png"))
    if len(files) != n:
        sys.exit(f"SAM3: expected {n} masks, got {len(files)}")
    masks, areas, purity, missed = [], [], [], []
    for i, fp in enumerate(files):
        m = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE)
        cv2.imwrite(str(dst["sam3"] / names[i]), m)
        ar, pu, ms = stats(m, frames(i))
        masks.append(m), areas.append(ar), purity.append(pu), missed.append(ms)
    why = {i: qc(areas, purity, missed, i) for i in range(n)}
    forced = {int(x) - 1 for x in a.force_fallback.split(",") if x}
    for i in forced:
        why[i] = why[i] + ["forced"]
    failed = sorted(i for i in range(n) if why[i])
    print(f"SAM3: {n} masks in {t_sam3:.0f}s; failed QC: {len(failed)} "
          f"{[(i + 1, why[i]) for i in failed]}", flush=True)

    # 2. SAM2 fallback, one propagation per run of failed frames
    source = ["sam3"] * n
    fb_log = []
    good = [i for i in range(n) if not why[i]]
    for k, (r0, r1) in enumerate(runs(failed), 1):
        before = [i for i in good if i < r0]
        after = [i for i in good if i > r1]
        if before:
            anchor, order = before[-1], [before[-1]] + list(range(r0, r1 + 1))
        elif after:
            anchor, order = after[0], [after[0]] + list(range(r1, r0 - 1, -1))
        else:
            sys.exit("no frame passed SAM3 QC; nothing to seed SAM2 from")
        tmp = f"{seg}_fb{k}"
        td = ROOT / "frames" / tmp
        shutil.rmtree(td, ignore_errors=True)
        td.mkdir()
        for j, i in enumerate(order):
            os.link(src / names[i], td / f"f_{j + 1:04d}.png")
        pos, neg = seed_prompts(masks[anchor], frames(anchor))
        print(f"fallback {k}: frames f_{r0 + 1:04d}-f_{r1 + 1:04d}, anchor f_{anchor + 1:04d} "
              f"({'forward' if anchor < r0 else 'backward'}), pos {pos}, neg {neg}", flush=True)
        shutil.rmtree(OUT / f"{tmp}_sam2", ignore_errors=True)
        rl.free_comfy()
        g2 = wf.build(tmp, fills=(), tag="sam2", prompts=[(0, pos, neg)], fps=rl.FILM_FPS)
        json.dump(g2, open(ROOT / "workflows" / f"{tmp}_sam2.json", "w"), indent=1)
        t0 = time.time()
        wf.submit(g2)
        dt = time.time() - t0
        out2 = sorted((OUT / f"{tmp}_sam2").glob("*_.png"))
        shutil.rmtree(td)
        if len(out2) != len(order):
            sys.exit(f"fallback {k}: expected {len(order)} masks, got {len(out2)}")
        rec = {"run": [r0 + 1, r1 + 1], "anchor": anchor + 1, "pos": pos, "neg": neg,
               "seconds": round(dt), "frames": {}}
        for j, i in enumerate(order[1:], 1):
            m2 = cv2.imread(str(out2[j]), cv2.IMREAD_GRAYSCALE)
            a2, p2, ms2 = stats(m2, frames(i))
            old = areas[i], purity[i], missed[i]
            areas[i], purity[i], missed[i] = a2, p2, ms2
            why2 = [w for w in qc(areas, purity, missed, i) if not w.startswith("jump")]
            s2, s3 = score(p2, ms2), score(old[1], old[2])
            if why[i] == ["forced"]:      # SAM3 was fine: SAM2 must pass and be about as good
                use2 = not why2 and s2 >= s3 - 0.02
            else:                         # SAM3 failed: SAM2 if it passes, else the better score
                use2 = not why2 or s2 > s3
            if use2:
                masks[i], source[i] = m2, "sam2"
            else:
                areas[i], purity[i], missed[i] = old
            rec["frames"][i + 1] = {"sam3": [old[0], round(old[1], 3), round(old[2], 3)],
                                    "sam2": [a2, round(p2, 3), round(ms2, 3)],
                                    "sam2_qc": why2, "used": source[i]}
        fb_log.append(rec)
        print(f"fallback {k}: {len(order) - 1} frames in {dt:.0f}s; used SAM2 on "
              f"{sum(1 for v in rec['frames'].values() if v['used'] == 'sam2')}", flush=True)

    # 3. final masks, composites, videos, log
    for i in range(n):
        cv2.imwrite(str(dst["mask"] / names[i]), masks[i])
        fr = frames(i)
        al = (masks[i].astype(np.float32) / 255)[..., None]
        for fill, val in rl.FILLS.items():
            cv2.imwrite(str(dst[fill] / names[i]), (fr * al + val * (1 - al)).astype(np.uint8))
    final_fail = [i + 1 for i in range(n) if qc(areas, purity, missed, i)]
    log = {"seg": seg, "prompt": a.prompt, "threshold": a.threshold, "frames": n,
           "sam3_seconds": round(t_sam3), "forced": sorted(i + 1 for i in forced),
           "sam3_failed": {i + 1: why[i] for i in failed}, "fallbacks": fb_log,
           "final_failing_qc": final_fail,
           "per_frame": [{"f": i + 1, "source": source[i], "area": areas[i],
                          "purity": round(purity[i], 3), "missed": round(missed[i], 3)} for i in range(n)]}
    json.dump(log, open(ROOT / "shots" / f"{seg}_sam3.json", "w"), indent=1)
    for fill, suffix in (("white", ""), ("black", "_black")):
        subprocess.run([rl.FFMPEG, "-v", "error", "-y", "-framerate", "24000/1001",
                        "-i", str(dst[fill] / "f_%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-crf", "18", str(ROOT / "out" / f"{seg}_sam3{suffix}.mp4")], check=True)
    print(f"DONE {seg}: SAM3 {source.count('sam3')}, SAM2 {source.count('sam2')}; "
          f"still failing QC: {final_fail}", flush=True)


if __name__ == "__main__":
    main()
