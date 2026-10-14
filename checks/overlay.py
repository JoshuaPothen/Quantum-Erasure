"""Tile mask-over-frame overlays for visual checks.
usage: python checks/overlay.py <shot> <tag> <out.jpg> <frame#> [<frame#> ...]
frame# is 1-based (matches f_%04d.png). Masks are read from ComfyUI's output
folder qe/<shot>_<tag>/mask_%05d_.png. When the prompt frame is later than
f_0001, SAM2 returns fewer masks, so pass --offset <first prompted index>.
"""
import cv2, numpy as np, sys, os

OUT = r"C:\Users\POTHEN\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output\qe"
args = sys.argv[1:]
offset = 0
if "--offset" in args:
    i = args.index("--offset"); offset = int(args[i + 1]); del args[i:i + 2]
shot, tag, dst, frames = args[0], args[1], args[2], [int(f) for f in args[3:]]
tiles = []
for f in frames:
    img = cv2.imread(f"frames/{shot}/f_{f:04d}.png")
    mp = os.path.join(OUT, f"{shot}_{tag}", f"mask_{f - offset:05d}_.png")
    m = cv2.imread(mp, cv2.IMREAD_GRAYSCALE)
    if m is None:
        m = np.zeros(img.shape[:2], np.uint8)
    a = (m.astype(np.float32) / 255)[..., None]
    red = np.zeros_like(img); red[..., 2] = 255
    ov = (img * (1 - 0.6 * a) + red * 0.6 * a).astype(np.uint8)
    cnts, _ = cv2.findContours((m > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(ov, cnts, -1, (0, 255, 255), 2)
    cv2.putText(ov, f"f_{f:04d}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 255, 0), 4)
    tiles.append(cv2.resize(ov, (960, 540)))
while len(tiles) % 2:
    tiles.append(np.zeros_like(tiles[0]))
rows = [np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)]
cv2.imwrite(dst, np.vstack(rows))
print("wrote", dst)
