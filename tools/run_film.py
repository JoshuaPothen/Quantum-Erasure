#!/usr/bin/env python3
"""
Full-film run (film/README.md): Pocahontas's hair only, white fill, one folder per segment.

Per segment of shots/shots_v1.csv (credits are skipped, they're kept as-is):
 1. extract frames through tools/frameio.py to film/work/segNNNN/ (deleted afterwards)
 2. presence check: SAM3 on every PRESENCE_NTH-th frame; if none of them has her hair
    the segment is all white and steps 3-4 are skipped (logged as "absent")
 3. SAM3 (main), in chunks of CHUNK frames, two prompts per frame:
      hair  "long black hair:4"       refine 1 -> GrowMask(1) -> blur(5, 2)   (docs/X02)
      her   "Native American woman:1" refine 0 -> identity mask
    final mask = hair kept only where it belongs to her (select_hers)
 4. QC every frame (purity / missed / jump / gap). SAM2 fallback on each run of failed
    frames, seeded from the nearest passing frame (run_sam3_shot.seed_prompts), only when the
    segment's override has "sam2": true -- off by default since README step 18
 5. white composite piped to ffmpeg -> film/segments/segNNNN/segNNNN.mp4; film indices
    with no picture (damaged span, seg 114) repeat the previous frame so audio stays in sync
 6. masks/, qc.json, sheet.jpg, README.md in the segment folder; one row in STATUS.csv

Usage: python tools/run_film.py [--from N] [--to M] [--only 5,224] [--redo]
Resumable: a segment with film/segments/segNNNN/qc.json is skipped unless --redo.
"""
import argparse
import csv
import json
import os
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
sys.path.insert(0, str(ROOT / "tools"))
import sam2_workflow as wf  # noqa: E402
import run_long_shot as rl  # noqa: E402
import run_sam3_shot as r3  # noqa: E402
from frameio import iter_frames, FPS  # noqa: E402

VIDEO = str(ROOT / "Pocahontas (1995) BDrip 1080p ENG-ITA MultiSub x264 blyuray -Shiv@.mkv")
OUT = rl.OUT
SEGS = ROOT / "film" / "segments"
WORK = ROOT / "film" / "work"
STATUS = SEGS / "STATUS.csv"
CHUNK = 40                  # frames per ComfyUI submission (120 ran RAM out on long segs, README step 11)
FB_MAX = 120                # longest SAM2 fallback propagation
PRESENCE_NTH = 6
HAIR_PROMPT = "long black hair:5"
THRESH = 0.4                # her hair scores >= 0.63 on the labelled probes (README step 5)
P_HER = 0.5                 # track-level P(Pocahontas) to keep a hair track
P_FRAG = 0.2                # a fragment touching her hair is kept from this P
TINT_PURITY = 0.5
r3.MIN_PURITY = 0.75        # X02's 0.85 failed daylight hair with blue highlight lines (seg 168: 0.79-0.85)
CLIP_PY = r"C:/Users/POTHEN/AppData/Local/Comfy-Desktop/ComfyUI-Installs/ComfyUI/ComfyUI/.venv/Scripts/python.exe"
MAX_GAP = 12                # an empty run this short between present frames is a dropout, not absence
DARK_BG = 0.30              # share of near-black background above which "missed" is meaningless
DARK_SCENE = 0.5            # share of present frames failing "missed" above which the scene is dark (README step 10)
STATUS_COLS = ["seg", "kind", "start", "end", "frames", "status", "present", "sam3", "sam2",
               "fail_after", "missing_idx", "seconds", "notes"]


def submit(graph, timeout=7200):
    """POST to ComfyUI and wait; raises (wf.submit calls sys.exit, which would end the batch)."""
    req = urllib.request.Request(f"{wf.COMFY}/prompt", data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    pid = json.load(urllib.request.urlopen(req))["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = json.load(urllib.request.urlopen(f"{wf.COMFY}/history/{pid}"))
        if pid in h:
            st = h[pid]["status"]
            if st["status_str"] != "success":
                err = [m[1] for m in st.get("messages", []) if m[0] == "execution_error"]
                raise RuntimeError(f"ComfyUI {st['status_str']}: {json.dumps(err)[:800]}")
            return h[pid]
        time.sleep(1)
    raise RuntimeError(f"ComfyUI prompt {pid} timed out")


def overrides():
    """film/overrides.json: {"<seg>": {"absent": true | "drop": [tracks] | "keep": [tracks] | "sam2": true | "hold_gaps": true, "why": "..."}},
    written after reviewing segment sheets (README step 8)."""
    p = ROOT / "film" / "overrides.json"
    return json.load(open(p)) if p.exists() else {}


def segments():
    return [r for r in csv.DictReader(open(ROOT / "shots" / "shots_v1.csv"))]


# ---------------------------------------------------------------- 1. frames
def extract(row, work):
    s, e = int(row["start_frame"]), int(row["end_frame"])
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    got = []
    for idx, fr in iter_frames(VIDEO, start_s=s / FPS - 1.0, end_s=e / FPS + 0.01):
        if s <= idx <= e:
            got.append(idx)
            cv2.imwrite(str(work / f"f_{len(got):04d}.png"), fr, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    return got, sorted(set(range(s, e + 1)) - set(got))


# ---------------------------------------------------------------- 2-3. SAM3 + identity
def sam3_graph(work, skip, cap, nth, tag):
    """Hair instances (individual masks, refine 1) + their scores/boxes via PreviewAny."""
    return {"load": {"class_type": "VHS_LoadImagesPath", "inputs": {
                "directory": str(work), "image_load_cap": cap, "skip_first_images": skip, "select_every_nth": nth}},
            "ck": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": r3.SAM3_CKPT}},
            "th": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ck", 1], "text": HAIR_PROMPT}},
            "dh": {"class_type": "SAM3_Detect", "inputs": {"model": ["ck", 0], "image": ["load", 0], "conditioning": ["th", 0],
                   "threshold": THRESH, "refine_iterations": 1, "individual_masks": True}},
            "ih": {"class_type": "MaskToImage", "inputs": {"mask": ["dh", 0]}},
            "sh": {"class_type": "SaveImage", "inputs": {"images": ["ih", 0], "filename_prefix": f"qe/{tag}/m"}},
            "ph": {"class_type": "PreviewAny", "inputs": {"source": ["dh", 1]}}}


def run_sam3(work, skip, cap, nth, tag="film"):
    """-> per frame: list of {"path": instance mask PNG in work/_inst, "small": bool mask at 1/4,
    "area", "score", "box": [x,y,w,h]}. Full-res masks stay on disk (RAM: 5 x 2 MB per frame)."""
    shutil.rmtree(OUT / tag, ignore_errors=True)
    try:
        outs = submit(sam3_graph(work, skip, cap, nth, tag))["outputs"]
    except RuntimeError as ex:
        # no instance in the whole batch -> SaveImage gets an empty tensor (seg 1118, README step 15)
        if '"node_id": "sh"' not in str(ex) or "out of bounds for dimension 0 with size 0" not in str(ex):
            raise
        sel = sorted(work.glob("f_*.png"))[skip::nth]
        return [[] for _ in (sel[:cap] if cap else sel)]
    boxes = json.loads(outs["ph"]["text"][0])
    files = sorted((OUT / tag).glob("*_.png"))
    if sum(len(b) for b in boxes) != len(files):
        raise RuntimeError(f"SAM3: {sum(len(b) for b in boxes)} boxes but {len(files)} masks")
    idir = work / "_inst"
    idir.mkdir(exist_ok=True)
    res, k = [], 0
    for f, fb in enumerate(boxes):
        fr = []
        for j, b in enumerate(fb):
            m = cv2.imread(str(files[k]), cv2.IMREAD_GRAYSCALE) > 127
            k += 1
            if m.sum() >= 200:
                path = idir / f"{tag}_{skip + f * nth:05d}_{j}.png"
                cv2.imwrite(str(path), m.astype(np.uint8) * 255, [cv2.IMWRITE_PNG_COMPRESSION, 1])
                fr.append({"path": path, "small": m[::4, ::4].copy(), "area": int(m.sum()),
                           "score": round(b["score"], 3), "box": [b["x"], b["y"], b["width"], b["height"]]})
        res.append(fr)
    shutil.rmtree(OUT / tag, ignore_errors=True)
    return res


class Identity:
    """P(instance is Pocahontas's hair): CLIP ViT-L/14 crop embedding (tools/clip_id.py, run as a
    server in ComfyUI's venv) -> logistic regression trained on film/id labels (tools/id_model.py)."""
    def __init__(self):
        import id_model
        X, y, _ = id_model.data()
        self.w = id_model.fit(X, y, 1e-3)
        self.predict = id_model.predict
        self.srv = subprocess.Popen([CLIP_PY, str(ROOT / "tools" / "clip_id.py")], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    def __call__(self, img_path, insts):
        if not insts:
            return
        self.srv.stdin.write(json.dumps({"img": str(img_path), "boxes": [i["box"] for i in insts], "emb": True}) + "\n")
        self.srv.stdin.flush()
        e = np.array(json.loads(self.srv.stdout.readline())["emb"], np.float32) * 10
        for i, p in zip(insts, self.predict(self.w, e)):
            i["p"] = round(float(p), 3)


def link_tracks(frames_inst):
    """Greedy IoU linking of instances between consecutive frames; sets inst["track"]."""
    nxt = 0
    prev = []
    for insts in frames_inst:
        used = set()
        for ins in sorted(insts, key=lambda d: -d["area"]):
            best, bi = 0.0, None
            small = ins["small"]
            for j, pv in enumerate(prev):
                if j in used:
                    continue
                inter = (small & pv["small"]).sum()
                iou = inter / max(1, (small | pv["small"]).sum())
                if iou > best:
                    best, bi = iou, j
            if bi is not None and best >= 0.3:
                ins["track"] = prev[bi]["track"]
                used.add(bi)
            else:
                ins["track"], nxt = nxt, nxt + 1
        prev = insts


def select_hers(frames_inst, ov=None):
    """Keep instances whose TRACK is hers (area-weighted mean P >= P_HER), plus fragments with
    P >= P_FRAG touching a kept instance in the same frame. Sets inst["hers"]; returns track P.
    ov: manual override from film/overrides.json, {"drop": [track ids], "keep": [track ids]}."""
    ov = ov or {}
    link_tracks(frames_inst)
    num, den = {}, {}
    for insts in frames_inst:
        for i in insts:
            num[i["track"]] = num.get(i["track"], 0) + i["area"] * i["p"]
            den[i["track"]] = den.get(i["track"], 0) + i["area"]
    tp = {t: num[t] / den[t] for t in num}
    k = np.ones((7, 7), np.uint8)
    for insts in frames_inst:
        for i in insts:
            i["hers"] = (tp[i["track"]] >= P_HER or i["track"] in ov.get("keep", []))                 and i["track"] not in ov.get("drop", [])
        mine = [i for i in insts if i["hers"]]
        if mine:
            near = cv2.dilate(np.any([i["small"] for i in mine], 0).astype(np.uint8), k) > 0
            for i in insts:
                if not i["hers"] and i["p"] >= P_FRAG and (i["small"] & near).any()                         and i["track"] not in ov.get("drop", []):
                    i["hers"] = True
    return tp


def frame_masks(insts):
    """(her bool mask, other characters' hair bool mask) at full res from the instance PNGs."""
    m = np.zeros((1080, 1920), bool)
    r = np.zeros_like(m)
    for i in insts:
        x = cv2.imread(str(i["path"]), cv2.IMREAD_GRAYSCALE) > 127
        if i["hers"]:
            m |= x
        else:
            r |= x
    return m, r & ~m


def soften(m):
    """GrowMask(1) + Gaussian blur(5, 2), as the X02 graph did in ComfyUI -> uint8 alpha."""
    g = cv2.dilate(m.astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
    return cv2.GaussianBlur(g, (wf.BLUR_KERNEL, wf.BLUR_KERNEL), wf.BLUR_SIGMA)


# ---------------------------------------------------------------- 4. QC
def stats(mask, frame, other=None):
    """(area, purity, missed) as run_sam3_shot.stats, except 'missed' ignores dark pixels that
    belong to OTHER characters' hair (rejected instances) and is 0 when most of the background
    is itself near-black (night scenes: every unmasked dark blob touches the hair)."""
    a, p, ms = r3.stats(mask, frame)
    if ms and other is not None and other.any():
        fr = frame.copy()
        fr[cv2.dilate(other.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0] = 255
        ms = r3.stats(mask, fr)[2]
    v = rl.value(frame)
    if float(((v < rl.DARK_V) & (mask <= 127)).mean()) > DARK_BG:
        ms = 0.0
    return a, p, ms


def qc_fail(areas, purity, missed, present, i, off=frozenset()):
    """Reasons frame i fails. Empty frames pass when she's absent; an empty run of
    <= MAX_GAP frames with hair on both sides is a dropout and fails. `off` names the
    checks switched off for the whole segment ("purity", "missed": tinted / dusk / dark scenes)."""
    if areas[i] < r3.MIN_PX:
        return ["gap"] if present[i] else []
    why = [w for w in r3.qc(areas, purity, missed, i) if w != "empty"]
    # per frame: purity < TINT_PURITY means the hair itself isn't dark (tinted light, seg 240:
    # purity 0.0 on correct masks), not spill -- a spill onto background keeps her dark hair in it
    if purity[i] < TINT_PURITY:
        off = {"purity", "missed"}
    return [w for w in why if w.split()[0] not in off]


def scene_off(areas, purity, missed, log):
    """Checks to switch off for the whole segment (README steps 6 and 10)."""
    pres = [i for i, a in enumerate(areas) if a >= r3.MIN_PX]
    if not pres:
        return set()
    med = float(np.median([purity[i] for i in pres]))
    off = set()
    if med < TINT_PURITY:
        log["notes"].append(f"tinted scene: median hair purity {med:.2f} < {TINT_PURITY}, purity/missed QC off")
        return {"purity", "missed"}
    if med < r3.MIN_PURITY:
        # dusk / far shots: her hair is lit or tiny, not near-black (segs 130, 165)
        log["notes"].append(f"dusk scene: median hair purity {med:.2f} < {r3.MIN_PURITY}, purity QC off")
        off.add("purity")
    share = sum(missed[i] > r3.MAX_MISSED for i in pres) / len(pres)
    if share >= DARK_SCENE:
        # night interiors: navy walls/sky below DARK_V touch her hair (segs 184, 187)
        log["notes"].append(f"dark scene: {share:.0%} of frames fail 'missed', missed QC off")
        off.add("missed")
    return off


def gap_flags(areas):
    """present[i]: frame i lies inside an empty run short enough to be a dropout."""
    n = len(areas)
    on = [a >= r3.MIN_PX for a in areas]
    present = [False] * n
    i = 0
    while i < n:
        if on[i]:
            i += 1
            continue
        j = i
        while j < n and not on[j]:
            j += 1
        if i > 0 and j < n and j - i <= MAX_GAP:
            for k in range(i, j):
                present[k] = True
        i = j
    return present


def fallback(work, names, masks, areas, purity, missed, why, frames, seg, log, others, off):
    """SAM2 propagation over each run of failed frames (docs/X02 step 3)."""
    n = len(names)
    source = log["source"]
    failed = sorted(i for i in range(n) if why[i])
    good = [i for i in range(n) if not why[i] and areas[i] >= r3.MIN_PX]
    runs = []
    for r0, r1 in r3.runs(failed):
        for c in range(r0, r1 + 1, FB_MAX):
            runs.append((c, min(r1, c + FB_MAX - 1)))
    for k, (r0, r1) in enumerate(runs, 1):
        before = [i for i in good if i < r0]
        after = [i for i in good if i > r1]
        if before and (not after or r0 - before[-1] <= after[0] - r1):
            anchor, order = before[-1], [before[-1]] + list(range(r0, r1 + 1))
        elif after:
            anchor, order = after[0], [after[0]] + list(range(r1, r0 - 1, -1))
        else:
            log["notes"].append(f"fallback {r0 + 1}-{r1 + 1}: no passing frame with hair to seed from")
            continue
        tmp = f"_fb_{seg}_{k}"
        td = ROOT / "frames" / tmp
        shutil.rmtree(td, ignore_errors=True)
        td.mkdir()
        for j, i in enumerate(order):
            os.link(work / names[i], td / f"f_{j + 1:04d}.png")
        try:
            pos, neg = r3.seed_prompts(masks[anchor], frames(anchor))
        except Exception as ex:  # seed too small / no dark pixels
            log["notes"].append(f"fallback {r0 + 1}-{r1 + 1}: no seed prompts ({ex})")
            shutil.rmtree(td)
            continue
        if not pos:
            log["notes"].append(f"fallback {r0 + 1}-{r1 + 1}: seed has no hair-dark point")
            shutil.rmtree(td)
            continue
        shutil.rmtree(OUT / f"{tmp}_sam2", ignore_errors=True)
        rl.free_comfy()
        t0 = time.time()
        submit(wf.build(tmp, fills=(), tag="sam2", prompts=[(0, pos, neg)], fps=rl.FILM_FPS))
        out2 = sorted((OUT / f"{tmp}_sam2").glob("*_.png"))
        shutil.rmtree(td)
        if len(out2) != len(order):
            shutil.rmtree(OUT / f"{tmp}_sam2", ignore_errors=True)
            log["notes"].append(f"fallback {r0 + 1}-{r1 + 1}: SAM2 returned {len(out2)}/{len(order)} masks")
            continue
        used = 0
        for j, i in enumerate(order[1:], 1):
            m2 = cv2.imread(str(out2[j]), cv2.IMREAD_GRAYSCALE)
            a2, p2, ms2 = stats(m2, frames(i), others[i])
            old = areas[i], purity[i], missed[i]
            areas[i], purity[i], missed[i] = a2, p2, ms2
            why2 = [w for w in qc_fail(areas, purity, missed, [False] * n, i, off) if not w.startswith("jump")]
            why2 = why2 or (["empty"] if a2 < r3.MIN_PX else [])
            # a smaller, "purer" SAM2 mask that drops hair must not win (seg 171): unless SAM3 was
            # empty or jumped, SAM2 needs >= 85% of SAM3's area
            shrink = old[0] >= r3.MIN_PX and a2 < 0.85 * old[0] and not any(
                w.startswith("jump") for w in why[i])
            if not shrink and (not why2 or (r3.score(p2, ms2) > r3.score(old[1], old[2]) and a2 >= r3.MIN_PX)):
                masks[i], source[i] = m2, "sam2"
                used += 1
            else:
                areas[i], purity[i], missed[i] = old
        shutil.rmtree(OUT / f"{tmp}_sam2", ignore_errors=True)
        log["fallbacks"].append({"run": [r0 + 1, r1 + 1], "anchor": anchor + 1, "dir":
                                 "forward" if anchor < r0 else "backward", "frames": r1 - r0 + 1,
                                 "used_sam2": used, "seconds": round(time.time() - t0)})


# ---------------------------------------------------------------- 5-6. outputs
def encode(dst_mp4, work, names, masks, film_idx, missing, s, e):
    """White composite for every film index s..e; missing indices repeat the previous frame."""
    p = subprocess.Popen([rl.FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                          "-s", "1920x1080", "-framerate", "24000/1001", "-i", "-",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                          "-g", "48", str(dst_mp4)], stdin=subprocess.PIPE)
    by_idx = {f: i for i, f in enumerate(film_idx)}
    last = None
    for f in range(s, e + 1):
        i = by_idx.get(f)
        if i is not None:
            fr = cv2.imread(str(work / names[i]))
            if masks is None or masks[i] is None:
                last = np.full_like(fr, 255)
            else:
                al = (masks[i].astype(np.float32) / 255)[..., None]
                last = (fr * al + 255 * (1 - al)).astype(np.uint8)
        elif last is None:
            last = np.full((1080, 1920, 3), 255, np.uint8)
        p.stdin.write(last.tobytes())
    p.stdin.close()
    if p.wait():
        raise RuntimeError(f"ffmpeg failed on {dst_mp4}")


def sheet(path, work, names, masks, picks, label):
    """2 rows x len(picks): original with mask outline, white composite."""
    top, bot = [], []
    for i in picks:
        fr = cv2.imread(str(work / names[i]))
        m = masks[i] if masks is not None and masks[i] is not None else np.zeros(fr.shape[:2], np.uint8)
        o = fr.copy()
        cs, _ = cv2.findContours((m > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(o, cs, -1, (0, 0, 255), 4)
        cv2.putText(o, f"f_{i + 1:04d}", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 255, 255), 5)
        al = (m.astype(np.float32) / 255)[..., None]
        top.append(cv2.resize(o, (384, 216), interpolation=cv2.INTER_AREA))
        bot.append(cv2.resize((fr * al + 255 * (1 - al)).astype(np.uint8), (384, 216), interpolation=cv2.INTER_AREA))
    img = np.vstack([np.hstack(top), np.hstack(bot)])
    bar = np.full((40, img.shape[1], 3), 32, np.uint8)
    cv2.putText(bar, label, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.imwrite(str(path), np.vstack([bar, img]), [cv2.IMWRITE_JPEG_QUALITY, 85])


def seg_readme(d, row, log):
    L = [f"# Segment {int(row['seg'])} ({row['kind']})", "",
         f"Film frames {row['start_frame']}-{row['end_frame']} ({row['frames']} frames, "
         f"{float(row['start_s']) / 60:.0f}:{float(row['start_s']) % 60:04.1f}-"
         f"{float(row['end_s']) / 60:.0f}:{float(row['end_s']) % 60:04.1f}).", "",
         f"**Status: {log['status']}**", "",
         "| | |", "|---|---|",
         f"| Frames with her hair | {log['present']} / {log['n']} |",
         f"| Mask source | SAM3 {log['count']['sam3']}, SAM2 fallback {log['count']['sam2']} |",
         f"| Frames still failing QC | {len(log['fail_after'])} {log['fail_after'][:20]} |",
         f"| Film indices with no picture (held) | {len(log['missing'])} |",
         f"| Time | {log['seconds']} s |", "",
         "![QC sheet](sheet.jpg)", "",
         "Top: source with the final mask outlined in red. Bottom: white-fill output.", ""]
    if log["fallbacks"]:
        L += ["## SAM2 fallbacks", "", "| Frames | Anchor | Direction | SAM2 used |", "|---|---|---|---|"]
        L += [f"| {f['run'][0]}-{f['run'][1]} | {f['anchor']} | {f['dir']} | {f['used_sam2']}/{f['frames']} |"
              for f in log["fallbacks"]]
        L.append("")
    if log["notes"]:
        L += ["## Issues", ""] + [f"- {x}" for x in log["notes"]] + [""]
    (d / "README.md").write_text("\n".join(L), encoding="utf-8")


def status_row(row, log):
    new = not STATUS.exists()
    with open(STATUS, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(STATUS_COLS)
        w.writerow([row["seg"], row["kind"], row["start_frame"], row["end_frame"], row["frames"],
                    log["status"], log["present"], log["count"]["sam3"], log["count"]["sam2"],
                    len(log["fail_after"]), len(log["missing"]), log["seconds"], " | ".join(log["notes"])])


# ---------------------------------------------------------------- driver
def process(row, ident):
    seg = f"seg{int(row['seg']):04d}"
    d = SEGS / seg
    work = WORK / seg
    t0 = time.time()
    shutil.rmtree(d, ignore_errors=True)
    (d / "masks").mkdir(parents=True)
    s, e = int(row["start_frame"]), int(row["end_frame"])
    film_idx, missing = extract(row, work)
    n = len(film_idx)
    names = [f"f_{i + 1:04d}.png" for i in range(n)]
    frames = lambda i: cv2.imread(str(work / names[i]))  # noqa: E731
    log = {"seg": seg, "n": n, "missing": missing, "notes": [], "fallbacks": [],
           "source": ["none"] * n, "status": "", "fail_after": []}
    if missing:
        log["notes"].append(f"{len(missing)} film indices have no picture (damaged source): "
                            f"{missing[0]}-{missing[-1]}; the previous frame is held")

    # 2. presence check on every PRESENCE_NTH-th frame
    pres = run_sam3(work, 0, 0, PRESENCE_NTH, "filmp")
    for f, insts in enumerate(pres):
        ident(work / names[f * PRESENCE_NTH], insts)
    best = max((i["p"] for insts in pres for i in insts), default=0.0)
    masks = None
    log["presence_best_p"] = round(best, 3)
    ov = overrides().get(str(int(row["seg"])), {})
    if ov:
        log["override"] = ov
        log["notes"].append(f"manual override: {ov.get('why', ov)}")
    if best < P_HER or ov.get("absent"):
        log["status"], log["present"] = "absent", 0
        nh = sum(1 for insts in pres if insts)
        if nh:
            log["notes"].append(f"hair on {nh}/{len(pres)} presence frames, none of it hers (best P {best:.2f})")
    else:
        # 3. SAM3 on every frame, identity per instance, tracks across the segment
        allinst = []
        for c in range(0, n, CHUNK):
            res = run_sam3(work, c, min(CHUNK, n - c), 1)
            if len(res) != min(CHUNK, n - c):
                raise RuntimeError(f"{seg}: SAM3 chunk at {c} returned {len(res)} frames")
            for k, insts in enumerate(res):
                ident(work / names[c + k], insts)
            allinst += res
        tp = select_hers(allinst, ov)
        masks, others, areas, purity, missed = [], [], [], [], []
        for i, insts in enumerate(allinst):
            m, r = frame_masks(insts)
            a_ = soften(m)
            a, p_, ms = stats(a_, frames(i), r)
            masks.append(a_), others.append(r), areas.append(a), purity.append(p_), missed.append(ms)
        log["tracks"] = {int(t): round(p, 3) for t, p in tp.items()}
        log["n_other_frames"] = sum(1 for r in others if r.sum() >= r3.MIN_PX)
        log["source"] = ["sam3" if a >= r3.MIN_PX else "none" for a in areas]
        off = scene_off(areas, purity, missed, log)
        log["qc_off"] = sorted(off)
        present = gap_flags(areas)
        why = [qc_fail(areas, purity, missed, present, i, off) for i in range(n)]
        log["sam3_failed"] = {i + 1: why[i] for i in range(n) if why[i]}
        if any(why) and ov.get("sam2"):  # off by default: SAM2 never beat SAM3 in review (README step 18)
            fallback(work, names, masks, areas, purity, missed, why, frames, seg, log, others, off)
        present = gap_flags(areas)
        if ov.get("hold_gaps"):
            # dropouts of <= MAX_GAP frames with hair on both sides: hold the last mask (seg 1250, README step 17)
            held = 0
            for i in range(1, n):
                if present[i] and areas[i] < r3.MIN_PX and areas[i - 1] >= r3.MIN_PX:
                    masks[i], areas[i], purity[i], missed[i] = masks[i - 1], areas[i - 1], purity[i - 1], missed[i - 1]
                    log["source"][i] = "hold"
                    held += 1
            log["notes"].append(f"hold_gaps: {held} dropout frames hold the previous mask")
            present = gap_flags(areas)
        log["fail_after"] = [i + 1 for i in range(n) if qc_fail(areas, purity, missed, present, i, off)]
        log["present"] = sum(1 for a in areas if a >= r3.MIN_PX)
        log["status"] = "ok" if not log["fail_after"] else "check"
        if log["n_other_frames"]:
            log["notes"].append(f"other characters' hair erased on {log['n_other_frames']} frames")
        log["per_frame"] = [{"f": i + 1, "film": film_idx[i], "src": log["source"][i], "area": areas[i],
                             "purity": round(purity[i], 3), "missed": round(missed[i], 3),
                             "inst": [[x["track"], x["score"], x["p"], int(x["hers"])] for x in allinst[i]]}
                            for i in range(n)]
        for i in range(n):
            cv2.imwrite(str(d / "masks" / names[i]), masks[i])

    # 5-6
    encode(d / f"{seg}.mp4", work, names, masks, film_idx, missing, s, e)
    picks = sorted({round(x * (n - 1) / 7) for x in range(8)})
    log["count"] = {"sam3": log["source"].count("sam3"), "sam2": log["source"].count("sam2")}
    log["seconds"] = round(time.time() - t0)
    sheet(d / "sheet.jpg", work, names, masks, picks,
          f"{seg}  {log['status']}  present {log['present']}/{n}  sam3 {log['count']['sam3']}  "
          f"sam2 {log['count']['sam2']}  fail {len(log['fail_after'])}")
    json.dump(log, open(d / "qc.json", "w"), indent=1)
    seg_readme(d, row, log)
    status_row(row, log)
    shutil.rmtree(work, ignore_errors=True)
    print(f"{seg} {row['kind']} {n}f: {log['status']} present {log['present']} sam3 {log['count']['sam3']} "
          f"sam2 {log['count']['sam2']} fail {len(log['fail_after'])} in {log['seconds']}s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="a", type=int, default=1)
    ap.add_argument("--to", dest="b", type=int, default=10 ** 6)
    ap.add_argument("--only", default="")
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    only = {int(x) for x in a.only.split(",") if x}
    SEGS.mkdir(parents=True, exist_ok=True)
    ident = Identity()
    for row in segments():
        k = int(row["seg"])
        if row["kind"] == "credits" or (only and k not in only) or not (a.a <= k <= a.b):
            continue
        if (SEGS / f"seg{k:04d}" / "qc.json").exists() and not a.redo:
            continue
        for attempt in (1, 2):
            try:
                process(row, ident)
                break
            except Exception as ex:
                print(f"seg{k:04d} attempt {attempt} FAILED: {ex!r}", flush=True)
                rl.free_comfy()
                time.sleep(10)
        else:
            with open(SEGS / "ERRORS.txt", "a") as f:
                f.write(f"seg{k:04d}: failed twice\n")


if __name__ == "__main__":
    main()
