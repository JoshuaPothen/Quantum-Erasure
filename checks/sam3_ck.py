"""SAM3 text-prompt checkpoint on every Nth frame of a segment (docs/X02 step 2)."""
import json, sys, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sam2_workflow as wf

seg, nth, prompts = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
ROOT = Path(wf.ROOT)
OUT = Path(r"C:/Users/POTHEN/AppData/Local/Comfy-Desktop/ComfyUI-Shared/output/qe")
g = {"1": {"class_type": "VHS_LoadImagesPath", "inputs": {"directory": str(ROOT / "frames" / seg),
           "image_load_cap": 0, "skip_first_images": 0, "select_every_nth": nth}},
     "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sam3.1_multiplex_fp16.safetensors"}}}
for i, p in enumerate(prompts):
    t, d = str(10 + 3 * i), str(11 + 3 * i)
    g[t] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1], "text": p}}
    g[d] = {"class_type": "SAM3_Detect", "inputs": {"model": ["2", 0], "image": ["1", 0], "conditioning": [t, 0],
            "threshold": 0.3, "refine_iterations": 2, "individual_masks": False}}
    g[str(12 + 3 * i)] = {"class_type": "SaveImage", "inputs": {"filename_prefix": f"qe/{seg}_sam3ck_{i}/mask",
            "images": [str(20 + i), 0]}}
    g[str(20 + i)] = {"class_type": "MaskToImage", "inputs": {"mask": [d, 0]}}
    shutil.rmtree(OUT / f"{seg}_sam3ck_{i}", ignore_errors=True)
json.dump(g, open(ROOT / "workflows" / f"{seg}_sam3ck.json", "w"), indent=1)
wf.submit(g)
