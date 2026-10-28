"""Review sheet of a segment's FAILING frames (the QC sheet.jpg only shows 8 evenly spaced ones).

Each tile: the original frame dimmed, the final mask in green with its outline, and a caption
with frame number, source (sam3/sam2/none), area, purity, missed and the failure reasons.

Usage: python checks/fail_frames.py 1007 [out.jpg] [--n 8] [--frames 1,50,120]
Default out: film/img/03_review_segNNNN.jpg
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from frameio import iter_frames  # noqa: E402
import run_film as rf  # noqa: E402

TILE_W = 640


def reasons(x, off):
    why = []
    if x["area"] < rf.r3.MIN_PX:
        return ["gap"]
    if x["purity"] < rf.r3.MIN_PURITY and "purity" not in off:
        why.append(f"purity {x['purity']:.2f}")
    if x["missed"] > rf.r3.MAX_MISSED and "missed" not in off:
        why.append(f"missed {x['missed']:.2f}")
    return why or ["jump"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seg", type=int)
    ap.add_argument("out", nargs="?")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--frames", default="")
    a = ap.parse_args()
    d = ROOT / "film" / "segments" / f"seg{a.seg:04d}"
    q = json.load(open(d / "qc.json"))
    pf, off = q["per_frame"], set(q.get("qc_off", []))
    if a.frames:
        picks = [int(x) for x in a.frames.split(",")]
    else:
        fa = q["fail_after"]
        picks = [fa[round(i * (len(fa) - 1) / max(1, a.n - 1))] for i in range(min(a.n, len(fa)))]
        picks = sorted(set(picks))
    want = {pf[f - 1]["film"]: f for f in picks}
    s, e = min(want), max(want)
    tiles = {}
    for idx, fr in iter_frames(rf.VIDEO, start_s=s / rf.FPS - 1.0, end_s=e / rf.FPS + 0.01):
        if idx not in want:
            continue
        f = want[idx]
        x = pf[f - 1]
        m = cv2.imread(str(d / "masks" / f"f_{f:04d}.png"), cv2.IMREAD_GRAYSCALE)
        v = (fr * 0.55).astype(np.uint8)
        hair = m > 127
        v[hair] = (0.5 * v[hair] + 0.5 * np.array([60, 255, 60])).astype(np.uint8)
        cs, _ = cv2.findContours(hair.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(v, cs, -1, (0, 255, 0), 3)
        v = cv2.resize(v, (TILE_W, TILE_W * 9 // 16), interpolation=cv2.INTER_AREA)
        top = np.zeros((44, TILE_W, 3), np.uint8)
        cv2.putText(top, f"f{f} film {idx}  {x['src']}  area {x['area']}", (6, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(top, "  ".join(reasons(x, off)), (6, 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 160, 255), 1, cv2.LINE_AA)
        tiles[f] = np.vstack([top, v])
        if len(tiles) == len(want):
            break
    order = [tiles[f] for f in sorted(tiles)]
    while len(order) % 4:
        order.append(np.zeros_like(order[0]))
    rows = [np.hstack(order[i:i + 4]) for i in range(0, len(order), 4)]
    out = Path(a.out) if a.out else ROOT / "film" / "img" / f"03_review_seg{a.seg:04d}.jpg"
    cv2.imwrite(str(out), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(out, "frames", sorted(tiles))


if __name__ == "__main__":
    main()
