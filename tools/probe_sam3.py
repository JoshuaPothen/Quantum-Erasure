#!/usr/bin/env python3
"""
Triage pass (film/README step 3): SAM3 on the 3 probe frames per segment, per INSTANCE.
Prompts "long black hair:4" and "Native American woman:4", threshold 0.2, refine 0,
individual masks. Scores and boxes come back through a PreviewAny node on SAM3_Detect's
BOUNDING_BOX output; instance masks are split per frame by those counts.
Writes film/probe/inst/f<idx>.json  {"hair": [{score, box, area, dark}], "woman": [...]}
       film/probe/inst/f<idx>_<kind><k>.png  (480x270 instance masks)
Usage: python tools/probe_sam3.py [--chunk 150]
"""
import json, shutil, sys, time, urllib.request
from pathlib import Path
import cv2, numpy as np
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import run_long_shot as rl  # noqa: E402

COMFY = "http://127.0.0.1:8188"
OUT = rl.OUT
PROMPTS = {"hair": "long black hair:4", "woman": "Native American woman:4"}
src = ROOT / "film" / "probe" / "full"
idir = ROOT / "film" / "probe" / "inst"
idir.mkdir(exist_ok=True)
CH = int(sys.argv[sys.argv.index("--chunk") + 1]) if "--chunk" in sys.argv else 150


def submit(g):
    req = urllib.request.Request(f"{COMFY}/prompt", data=json.dumps({"prompt": g}).encode(),
                                 headers={"Content-Type": "application/json"})
    pid = json.load(urllib.request.urlopen(req))["prompt_id"]
    while True:
        h = json.load(urllib.request.urlopen(f"{COMFY}/history/{pid}"))
        if pid in h:
            if h[pid]["status"]["status_str"] != "success":
                raise RuntimeError(str(h[pid]["status"])[:1500])
            return h[pid]["outputs"]
        time.sleep(2)


todo = [p for p in sorted(src.glob("f*.jpg")) if not (idir / f"{p.stem}.json").exists()]
print(f"{len(todo)} probes to do", flush=True)
for c0 in range(0, len(todo), CH):
    batch = todo[c0:c0 + CH]
    tmp = ROOT / "film" / "probe" / "_batch"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    for p in batch:
        shutil.copy(p, tmp / p.name)
    g = {"load": {"class_type": "VHS_LoadImagesPath", "inputs": {"directory": str(tmp), "image_load_cap": 0,
                  "skip_first_images": 0, "select_every_nth": 1}},
         "ck": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sam3.1_multiplex_fp16.safetensors"}}}
    for k, p in PROMPTS.items():
        g[f"t{k}"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ck", 1], "text": p}}
        g[f"d{k}"] = {"class_type": "SAM3_Detect", "inputs": {"model": ["ck", 0], "image": ["load", 0],
                      "conditioning": [f"t{k}", 0], "threshold": 0.2, "refine_iterations": 0, "individual_masks": True}}
        g[f"m{k}"] = {"class_type": "MaskToImage", "inputs": {"mask": [f"d{k}", 0]}}
        g[f"s{k}"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": f"qe/probe_{k}/m", "images": [f"m{k}", 0]}}
        g[f"p{k}"] = {"class_type": "PreviewAny", "inputs": {"source": [f"d{k}", 1]}}
        shutil.rmtree(OUT / f"probe_{k}", ignore_errors=True)
    t = time.time()
    outs = submit(g)
    res = {}
    for k in PROMPTS:
        boxes = json.loads(outs[f"p{k}"]["text"][0])
        files = sorted((OUT / f"probe_{k}").glob("*_.png"))
        assert sum(len(b) for b in boxes) == len(files), (k, sum(len(b) for b in boxes), len(files))
        res[k] = (boxes, files)
    off = {k: 0 for k in PROMPTS}
    for i, p in enumerate(batch):
        v = rl.value(cv2.imread(str(p)))
        rec = {}
        for k in PROMPTS:
            boxes, files = res[k]
            rec[k] = []
            for j, b in enumerate(boxes[i]):
                m = cv2.imread(str(files[off[k] + j]), 0) > 127
                a = int(m.sum())
                rec[k].append({"score": round(b["score"], 3), "box": [round(b["x"]), round(b["y"]),
                               round(b["width"]), round(b["height"])], "area": a,
                               "dark": round(float((v[m] < 40).mean()), 3) if a else 0.0})
                cv2.imwrite(str(idir / f"{p.stem}_{k}{j}.png"),
                            cv2.resize(m.astype(np.uint8) * 255, (480, 270), interpolation=cv2.INTER_AREA))
            off[k] += len(boxes[i])
        json.dump(rec, open(idir / f"{p.stem}.json", "w"))
    shutil.rmtree(tmp)
    print(f"{c0 + len(batch)}/{len(todo)} in {time.time() - t:.0f}s", flush=True)
