"""CLIP ViT-L/14 identity scoring of hair-instance crops (film/README step 4).
Runs in ComfyUI's venv (CUDA torch + transformers), not the system python:
  <comfy .venv python> tools/clip_id.py serve      -> reads JSON jobs on stdin, one per line
  job: {"img": path, "boxes": [[x,y,w,h],...]}  -> reply {"p": [p_pocahontas, ...], "probs": [[...]]}
"""
import json, os, sys
os.environ.setdefault("HF_HUB_OFFLINE", "1")
import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

NAME = "openai/clip-vit-large-patch14"
LABELS = ["Pocahontas from the Disney movie", "Nakoma, Pocahontas's friend", "an old Native American woman",
          "a Native American man", "Chief Powhatan", "a Native American child", "John Smith",
          "an English settler", "a raccoon", "a landscape"]
dev = "cuda"
model = CLIPModel.from_pretrained(NAME, torch_dtype=torch.float16).to(dev).eval()
proc = CLIPProcessor.from_pretrained(NAME)
with torch.no_grad():
    t = proc(text=[f"a cartoon picture of {x}" for x in LABELS], return_tensors="pt", padding=True).to(dev)
    tf = model.text_projection(model.text_model(**t).pooler_output)
    tf = tf / tf.norm(dim=-1, keepdim=True)


def crop(im, b, pad=0.35):
    x, y, w, h = b
    s = max(w, h) * (1 + 2 * pad)
    cx, cy = x + w / 2, y + h / 2
    W, H = im.size
    l, t_ = max(0, cx - s / 2), max(0, cy - s / 2)
    return im.crop((int(l), int(t_), int(min(W, cx + s / 2)), int(min(H, cy + s / 2))))


def score(img, boxes):
    im = Image.open(img).convert("RGB")
    crops = [crop(im, b) for b in boxes]
    if not crops:
        return {"p": [], "probs": []}
    with torch.no_grad():
        x = proc(images=crops, return_tensors="pt").to(dev)
        f = model.visual_projection(model.vision_model(pixel_values=x["pixel_values"].half()).pooler_output)
        f = f / f.norm(dim=-1, keepdim=True)
        pr = (100 * f @ tf.T).softmax(-1).float().cpu().numpy()
    return {"p": [round(float(p[0]), 4) for p in pr], "probs": pr.round(3).tolist(),
            "emb": f.float().cpu().numpy().round(4).tolist()}


if __name__ == "__main__":
    for line in sys.stdin:
        job = json.loads(line)
        r = score(job["img"], job["boxes"])
        if not job.get("emb"):
            r.pop("emb", None)
        print(json.dumps(r), flush=True)
