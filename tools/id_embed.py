#!/usr/bin/env python3
"""CLIP-embed every instance in film/id/instances.csv (tools/clip_id.py in ComfyUI's venv);
caches film/id/emb.npy (rows = instance id). Usage: python tools/id_embed.py"""
import csv, json, subprocess
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
PY = r"C:/Users/POTHEN/AppData/Local/Comfy-Desktop/ComfyUI-Installs/ComfyUI/ComfyUI/.venv/Scripts/python.exe"
D = ROOT / "film" / "id"
rows = list(csv.DictReader(open(D / "instances.csv")))
ep = D / "emb.npy"
E = np.load(ep) if ep.exists() else np.zeros((0, 768), np.float32)
if len(E) < len(rows):
    srv = subprocess.Popen([PY, str(ROOT / "tools" / "clip_id.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True)
    new = []
    for r in rows[len(E):]:
        srv.stdin.write(json.dumps({"img": str(ROOT / "film" / "probe" / "full" / f"f{int(r['film_idx']):06d}.jpg"),
                                    "boxes": [[float(r[c]) for c in "xywh"]], "emb": True}) + "\n")
        srv.stdin.flush()
        new.append(json.loads(srv.stdout.readline())["emb"][0])
    srv.stdin.close()
    E = np.vstack([E, np.array(new, np.float32)])
    np.save(ep, E)
print(E.shape)
