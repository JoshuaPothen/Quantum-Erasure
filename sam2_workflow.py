#!/usr/bin/env python3
"""
Build (and optionally submit) the ComfyUI API-format SAM2 hair-segmentation
workflow for one shot.

Graph: VHS_LoadImagesPath -> Sam2VideoSegmentationAddPoints (chained, one per
prompt frame) -> Sam2VideoSegmentation -> GrowMask -> ImpactGaussianBlurMask
-> [SaveImage masks] + ImageCompositeMasked (white / black fill)
-> [SaveImage comps] + VHS_VideoCombine (50fps h264).

Prompts live in PROMPTS below:
{shot: [(frame_index, positives, negatives[, object_index])]}.
Coordinates are pixel coords in the 1920x1080 source frame; frame_index is
0-based (f_0001.png == index 0). Corrective prompts are just extra entries.

Usage:
  python sam2_workflow.py <shot> [--cap N] [--fills white,black] [--tag TAG] [--submit]
"""
import argparse
import json
import os
import sys
import time
import urllib.request

COMFY = "http://127.0.0.1:8188"
ROOT = os.path.dirname(os.path.abspath(__file__))

MODEL = "sam2.1_hiera_large.safetensors"
PRECISION = "bf16"
GROW_PX = 1           # SAM2 edges are already tight; 1px guards the ink outline
BLUR_KERNEL = 5       # ~ Test 1's 2px feather
BLUR_SIGMA = 2.0
FPS = 50
FILL_COLORS = {"white": 0xFFFFFF, "black": 0x000000}

PROMPTS = {
    "shot26": [
        # f_0001: mid cross-dissolve from John Smith; only points on her hair
        (0, [(1150, 70), (1470, 700), (500, 850)],
            [(620, 520), (1250, 420), (350, 450)]),
        # f_0012: first clean frame, full-strength prompt on the hair mass
        (11, [(300, 780), (700, 450), (1150, 60), (1470, 650), (1000, 200)],
             [(1250, 420), (1200, 900), (500, 300), (1650, 400)]),
        # Tried and rejected: the thin strands crossing face/chest. As extra
        # positives on object 0 they're ignored; as their own object 1 the
        # mask floods the whole face/body. SAM2 can't hold a few-px strand.
    ],
    "shot5": [
        # f_0001: dissolve from canyon shot; small diving figure is the target,
        # the large outgoing figure's hair is a negative
        (0, [(722, 175)],
            [(1130, 300), (1750, 550), (720, 240)]),
        # f_0010: first clean sky frame
        (9, [(730, 180), (750, 160)],
            [(715, 240), (770, 285), (900, 200), (1800, 500)]),
        # Corrective prompts, waterfall portion. Uncorrected, SAM2 never leaked
        # onto the rock but shrank to the scalp cap from ~f_0075 on, dropping
        # the hair streaming up behind her head. Points picked on a 2.6x
        # contrast-boosted crop (hair is near-black, rock is navy).
        # Tried and rejected: a correction at f_0080 on (625,130),(635,190).
        # SAM2 read it as the rock face and flooded the left cliff f75-90,
        # and (conditioning frames act as memory both ways) blanked f62-70.
        (99, [(720, 150), (760, 250), (700, 320)],
             [(720, 420), (450, 300), (550, 50)]),
    ],
}


def pts(p):
    return json.dumps([{"x": x, "y": y} for x, y in p])


def build(shot, cap=0, fills=("white", "black"), tag="sam2", skip=0, prompts=None, fps=None):
    """skip/cap select a frame range of frames/<shot>/ (chunked runs);
    prompts overrides PROMPTS[shot]; fps overrides FPS (film = 24000/1001)."""
    g = {}
    prompts = PROMPTS[shot] if prompts is None else prompts
    fps = FPS if fps is None else fps
    nid = iter(range(1, 1000))

    def add(cls, **inputs):
        i = str(next(nid))
        g[i] = {"class_type": cls, "inputs": inputs}
        return i

    load = add("VHS_LoadImagesPath",
               directory=os.path.join(ROOT, "frames", shot),
               image_load_cap=cap, skip_first_images=skip, select_every_nth=1)
    model = add("DownloadAndLoadSAM2Model", model=MODEL, segmentor="video",
                device="cuda", precision=PRECISION)

    prev_model, prev_state = [model, 0], None
    for frame_idx, pos, neg, *obj in prompts:
        if cap and frame_idx >= cap:
            continue
        p = add("PrimitiveStringMultiline", value=pts(pos))
        n = add("PrimitiveStringMultiline", value=pts(neg))
        inputs = dict(sam2_model=prev_model, coordinates_positive=[p, 0],
                      coordinates_negative=[n, 0], frame_index=frame_idx,
                      object_index=obj[0] if obj else 0)
        if prev_state is None:
            inputs["image"] = [load, 0]
        else:
            inputs["prev_inference_state"] = prev_state
        a = add("Sam2VideoSegmentationAddPoints", **inputs)
        prev_model, prev_state = [a, 0], [a, 1]

    seg = add("Sam2VideoSegmentation", sam2_model=prev_model,
              inference_state=prev_state, keep_model_loaded=False)
    grow = add("GrowMask", mask=[seg, 0], expand=GROW_PX, tapered_corners=True)
    alpha = add("ImpactGaussianBlurMask", mask=[grow, 0],
                kernel_size=BLUR_KERNEL, sigma=BLUR_SIGMA)
    add("SaveImage", images=[add("MaskToImage", mask=[alpha, 0]), 0],
        filename_prefix=f"qe/{shot}_{tag}/mask")

    inv = add("InvertMask", mask=[alpha, 0])
    for fill in fills:
        solid = add("EmptyImage", width=1920, height=1080, batch_size=1,
                    color=FILL_COLORS[fill])
        # destination = frames, fill pasted where mask is NOT hair
        # == hair * alpha + fill * (1 - alpha)
        comp = add("ImageCompositeMasked", destination=[load, 0],
                   source=[solid, 0], x=0, y=0, resize_source=False,
                   mask=[inv, 0])
        add("SaveImage", images=[comp, 0],
            filename_prefix=f"qe/{shot}_comp_{fill}_{tag}/comp")
        add("VHS_VideoCombine", images=[comp, 0], frame_rate=fps, loop_count=0,
            filename_prefix=f"qe/{shot}_{tag}_{fill}", format="video/h264-mp4",
            pix_fmt="yuv420p", crf=18, save_metadata=False,
            trim_to_audio=False, pingpong=False, save_output=True)
    return g


def submit(graph):
    req = urllib.request.Request(f"{COMFY}/prompt",
                                 data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    pid = json.load(urllib.request.urlopen(req))["prompt_id"]
    print("prompt_id", pid, flush=True)
    t0 = time.time()
    while True:
        h = json.load(urllib.request.urlopen(f"{COMFY}/history/{pid}"))
        if pid in h:
            st = h[pid]["status"]
            print(f"status={st['status_str']} after {time.time()-t0:.0f}s")
            if st["status_str"] != "success":
                for m in st.get("messages", []):
                    if m[0] == "execution_error":
                        print(json.dumps(m[1], indent=1)[:3000])
                sys.exit(1)
            return h[pid]
        time.sleep(3)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("shot")
    ap.add_argument("--cap", type=int, default=0)
    ap.add_argument("--fills", default="white,black")
    ap.add_argument("--tag", default="sam2")
    ap.add_argument("--submit", action="store_true")
    a = ap.parse_args()
    graph = build(a.shot, a.cap, [f for f in a.fills.split(",") if f], a.tag)
    out = os.path.join(ROOT, "workflows", f"{a.shot}_{a.tag}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(graph, open(out, "w"), indent=1)
    print("wrote", out)
    if a.submit:
        submit(graph)
