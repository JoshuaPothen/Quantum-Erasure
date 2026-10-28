"""Time SAM3_Detect on the first N frames of a segment for prompt sets / refine settings."""
import sys, time, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sam2_workflow as wf
seg, n = sys.argv[1], int(sys.argv[2])
ROOT = Path(wf.ROOT)
def run(prompts, refine, tag):
    g = {"1": {"class_type": "VHS_LoadImagesPath", "inputs": {"directory": str(ROOT / "frames" / seg),
               "image_load_cap": n, "skip_first_images": 0, "select_every_nth": 1}},
         "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sam3.1_multiplex_fp16.safetensors"}}}
    for i, p in enumerate(prompts):
        g[f"t{i}"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1], "text": p}}
        g[f"d{i}"] = {"class_type": "SAM3_Detect", "inputs": {"model": ["2", 0], "image": ["1", 0], "conditioning": [f"t{i}", 0],
                "threshold": 0.3, "refine_iterations": refine, "individual_masks": False}}
        g[f"m{i}"] = {"class_type": "MaskToImage", "inputs": {"mask": [f"d{i}", 0]}}
        g[f"s{i}"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": f"qe/bench_{tag}_{i}/mask", "images": [f"m{i}", 0]}}
    t = time.time(); wf.submit(g); return time.time() - t
run(["long black hair:1"], 2, "warm")   # model load
for prompts, refine in [(["long black hair:1"], 2), (["long black hair:4", "Native American woman:1"], 2),
                        (["long black hair:4", "Native American woman:1"], 1), (["long black hair:4", "Native American woman:1"], 0)]:
    dt = run(prompts, refine, f"{len(prompts)}_{refine}")
    print(f"{prompts} refine={refine}: {dt:.1f}s = {dt / n:.2f} s/frame", flush=True)
