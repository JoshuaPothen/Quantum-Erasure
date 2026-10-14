#!/usr/bin/env python3
"""
Assemble the phase-01 deliverable shots/shots_v1.csv from:
  shots/cuts_adaptive3.csv    hard cuts (docs/01 step 8-9)
  shots/dissolves_v2.csv      flagged gradual transitions (docs/01 step 10)
  shots/damaged_spans.csv     frames with no / unreliable picture (docs/01 step 6)

Every film frame belongs to exactly one segment. kind:
  logo        studio logo before the film (frames < LOGO_END)
  shot        a shot
  transition  a flagged dissolve/fade span (split out of the shot it was in)
  credits     end credits (frames > STORY_END)
A shot fragment shorter than MIN_FRAG frames left by splitting is folded
into the adjacent transition. 'damaged' = segment overlaps a damaged span.

Usage: python tools/shots_build_v1.py
"""
import csv

FPS = 24000 / 1001
LOGO_END = 333        # fade from black into the film starts at 333 (step 10c)
STORY_END = 108726    # end of the final fade-out (dissolve 108702-108726, step 10c)
MIN_FRAG = 6

shots = [(int(r["start_frame"]), int(r["end_frame"])) for r in csv.DictReader(open("shots/cuts_adaptive3.csv"))]
# the stats CSV has no row for film frame 0 (no previous frame to diff), so the
# cut list starts at 1; frame 0 belongs to the first segment
shots[0] = (0, shots[0][1])
last = shots[-1][1]
diss = sorted((int(r["start_frame"]), int(r["end_frame"])) for r in csv.DictReader(open("shots/dissolves_v2.csv")))
spans = [(int(r["start_frame"]), int(r["end_frame"])) for r in csv.DictReader(open("shots/damaged_spans.csv"))]

segs = []
for s, e in shots:
    pieces, cur = [], s
    for p, q in diss:
        if q < cur or p > e:
            continue
        p, q = max(p, cur), min(q, e)
        if p > cur:
            pieces.append(["shot", cur, p - 1])
        pieces.append(["transition", p, q])
        cur = q + 1
    if cur <= e:
        pieces.append(["shot", cur, e])
    # fold tiny shot fragments into a neighbouring transition
    merged = []
    for k in pieces:
        if k[0] == "shot" and k[2] - k[1] + 1 < MIN_FRAG and len(pieces) > 1:
            if merged and merged[-1][0] == "transition":
                merged[-1][2] = k[2]
                continue
            k[0] = "transition"
        if merged and merged[-1][0] == "transition" and k[0] == "transition":
            merged[-1][2] = k[2]
        else:
            merged.append(k)
    segs += merged

# logo / credits boundaries split segments too
out = []
for kind, s, e in segs:
    for lo, hi, k2 in ((0, LOGO_END - 1, "logo"), (LOGO_END, STORY_END, None), (STORY_END + 1, last, "credits")):
        a, b = max(s, lo), min(e, hi)
        if a <= b:
            out.append([k2 or kind, a, b])
# merge consecutive logo / credits segments
final = []
for k in out:
    if final and k[0] in ("logo", "credits") and final[-1][0] == k[0] and final[-1][2] + 1 == k[1]:
        final[-1][2] = k[2]
    else:
        final.append(k)

assert final[0][1] == 0 and all(final[i][2] + 1 == final[i + 1][1] for i in range(len(final) - 1)), "gap/overlap"
with open("shots/shots_v1.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["seg", "kind", "start_frame", "end_frame", "frames", "start_s", "end_s", "damaged"])
    for i, (kind, s, e) in enumerate(final, 1):
        dmg = any(s <= q and e >= p for p, q in spans)
        w.writerow([i, kind, s, e, e - s + 1, f"{s/FPS:.3f}", f"{(e+1)/FPS:.3f}", int(dmg)])

from collections import Counter
c = Counter(k for k, _, _ in final)
sh = [e - s + 1 for k, s, e in final if k == "shot"]
sh.sort()
print(f"{len(final)} segments: {dict(c)}")
print(f"shots: median {sh[len(sh)//2]/FPS:.2f}s, longest {sh[-1]/FPS:.1f}s")
print("damaged segments:", [(i + 1, k, s, e) for i, (k, s, e) in enumerate(final)
                            if any(s <= q and e >= p for p, q in spans)])
