"""SAM3 union masks for several text prompts on every image of a folder; writes an
overlay sheet (one row per image, one column per prompt). Used for the identity
tests in docs/03_full_film_run.md.
Usage: python checks/sam3_prompts.py <img_dir> <sheet.jpg> "prompt a" "prompt b" ...
"""
import json, sys, shutil
from pathlib import Path
import cv2, numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sam2_workflow as wf

src, sheet, prompts = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]
OUT = Path(r"C:/Users/POTHEN/AppData/Local/Comfy-Desktop/ComfyUI-Shared/output/qe")
tag = "promptck"
g = {"1": {"class_type": "VHS_LoadImagesPath", "inputs": {"directory": str(src.resolve()),
           "image_load_cap": 0, "skip_first_images": 0, "select_every_nth": 1}},
     "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sam3.1_multiplex_fp16.safetensors"}}}
for i, p in enumerate(prompts):
    g[f"t{i}"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1], "text": p}}
    g[f"d{i}"] = {"class_type": "SAM3_Detect", "inputs": {"model": ["2", 0], "image": ["1", 0], "conditioning": [f"t{i}", 0],
            "threshold": 0.3, "refine_iterations": 2, "individual_masks": False}}
    g[f"m{i}"] = {"class_type": "MaskToImage", "inputs": {"mask": [f"d{i}", 0]}}
    g[f"s{i}"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": f"qe/{tag}_{i}/mask", "images": [f"m{i}", 0]}}
    shutil.rmtree(OUT / f"{tag}_{i}", ignore_errors=True)
wf.submit(g)
imgs = sorted(p for p in src.iterdir() if p.suffix.lower() in (".png", ".jpg"))
cols = [(0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255)]
rows = []
for k, ip in enumerate(imgs):
    im = cv2.imread(str(ip))
    cells = [im.copy()]
    for i in range(len(prompts)):
        m = cv2.imread(str(sorted((OUT / f"{tag}_{i}").glob("*_.png"))[k]), 0) > 127
        o = im.copy()
        o[m] = (0.45 * o[m] + 0.55 * np.array(cols[i % 4])).astype(np.uint8)
        cv2.putText(o, prompts[i], (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 4)
        cells.append(o)
    cv2.putText(cells[0], ip.stem, (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 4)
    rows.append(cv2.resize(np.hstack(cells), None, fx=0.2, fy=0.2, interpolation=cv2.INTER_AREA))
cv2.imwrite(sheet, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])
print("wrote", sheet)
