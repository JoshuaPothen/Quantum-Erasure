#!/usr/bin/env python3
"""
Gradual-transition (dissolve / fade) detector on the low-res cache
(shots/lowres_gray64x36.npy from tools/lowres_cache.py).

Stage 1 - local linearity (candidates). For each frame t, with A = t-K,
B = t+K, F = t:
  alpha    = <F-B, A-B> / |A-B|^2          F ~ alpha*A + (1-alpha)*B
  blend    = 1 - |F - blend(A,B)| / min(|F-A|, |F-B|)
  endpoint = rms |A-B|                       ~0 = static, test not applicable
Inside a steady dissolve AND in slow smooth motion, F sits halfway between
its neighbours: blend high, alpha ~0.5. So stage 1 finds both.

Stage 2 - global path (the discriminator). For a candidate run [s, e], take
the outer endpoints P = frame s-G, Q = frame e+G and fit every frame in the
run as a blend of P and Q. A dissolve/fade lies on the straight line from P
to Q: high global blend, alpha falling from ~1 to ~0. A pan or move does
not: its middle frames are not a mix of its first and last frames.

Hard cuts (shots/cuts_adaptive3.csv) split candidate runs.

Usage: python tools/detect_dissolves.py [--k 3] [--blend 0.4] [--minrun 6]
                                         [--gblend 0.6] [--drop 0.6]
Writes shots/dissolves_v2.csv, shots/dissolve_candidates.csv
"""
import csv
import sys

import numpy as np

arg = lambda name, d: type(d)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else d
K = arg("--k", 3)
BLEND_MIN = arg("--blend", 0.4)
END_MIN = arg("--endmin", 2.0)     # rms |A-B| (0..255); below = static
MIN_RUN = arg("--minrun", 6)
G = arg("--g", 2)                  # outer endpoints sit G frames outside the run
GBLEND_MIN = arg("--gblend", 0.6)  # mean global blend inside the run (strong path)
DROP_MIN = arg("--drop", 0.6)      # alpha must fall by at least this across the run
# weak path: animated layers keep moving during a hand-drawn dissolve, so real
# ones can score only 0.3-0.45 on global blend; accept those only when the
# picture really changes (rms |P-Q| >= WEAK_EP) - near-static shots with small
# motion fit any blend and scored up to 13.7 (docs/01 step 10d)
WEAK_GBLEND = arg("--weak-gblend", 0.3)
WEAK_EP = arg("--weak-ep", 14.0)
FPS = 24000 / 1001

X = np.load("shots/lowres_gray64x36.npy").astype(np.float32).reshape(-1, 36 * 64)
valid = np.load("shots/lowres_valid.npy")
N, npix = X.shape


def fit(F, A, B):
    """alpha, blend score of F (rows) as alpha*A + (1-alpha)*B."""
    AB = A - B
    den = (AB * AB).sum(-1)
    a = np.clip(((F - B) * AB).sum(-1) / np.maximum(den, 1e-6), 0, 1)
    resid = np.linalg.norm(F - (a[..., None] * A + (1 - a[..., None]) * B), axis=-1)
    near = np.minimum(np.linalg.norm(F - A, axis=-1), np.linalg.norm(F - B, axis=-1))
    return a, 1 - resid / np.maximum(near, 1e-6), np.sqrt(den / npix)


# ---- stage 1 ---------------------------------------------------------------
blend = np.full(N, np.nan, np.float32)
endp = np.full(N, np.nan, np.float32)
t = np.arange(K, N - K)
t = t[valid[t] & valid[t - K] & valid[t + K]]
_, b, e = fit(X[t], X[t - K], X[t + K])
blend[t], endp[t] = b, e
cuts = {int(r["start_frame"]) for r in csv.DictReader(open("shots/cuts_adaptive3.csv"))}
cand = (blend >= BLEND_MIN) & (endp >= END_MIN)
runs, i = [], 0
while i < N:
    if cand[i]:
        j = i
        while j + 1 < N and cand[j + 1] and (j + 1) not in cuts:
            j += 1
        if j - i + 1 >= MIN_RUN:
            runs.append((i, j))
        i = j + 1
    else:
        i += 1

# ---- stage 2 ---------------------------------------------------------------
found, rows = [], []
for s, e in runs:
    p, q = s - G, e + G
    if p < 0 or q >= N or not (valid[p] and valid[q]):
        continue
    fr = np.arange(s, e + 1)
    fr = fr[valid[fr]]
    a, gb, ep = fit(X[fr], X[p][None], X[q][None])
    drop = float(a[: max(1, len(a) // 4)].mean() - a[-max(1, len(a) // 4):].mean())
    mono = float(np.mean(np.diff(a) <= 0.02)) if len(a) > 1 else 0.0
    gbm = float(gb.mean())
    epm = float(ep[0])
    strong = gbm >= GBLEND_MIN
    weak = gbm >= WEAK_GBLEND and epm >= WEAK_EP
    is_diss = (strong or weak) and drop >= DROP_MIN and mono >= 0.8
    rows.append((s, e, e - s + 1, gbm, drop, mono, float(ep[0]), is_diss))
    if is_diss:
        found.append((p, q, e - s + 1, gbm, drop))

with open("shots/dissolve_candidates.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["start_frame", "end_frame", "frames", "global_blend", "alpha_drop", "alpha_monotone",
                "endpoint_rms", "is_dissolve", "start_s"])
    for s, e, n, gbm, drop, mono, ep, d in rows:
        w.writerow([s, e, n, f"{gbm:.2f}", f"{drop:.2f}", f"{mono:.2f}", f"{ep:.1f}", int(d), f"{s/FPS:.2f}"])
with open("shots/dissolves_v2.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["start_frame", "end_frame", "frames", "global_blend", "alpha_drop", "start_s", "end_s"])
    for p, q, n, gbm, drop in found:
        w.writerow([p, q, q - p + 1, f"{gbm:.2f}", f"{drop:.2f}", f"{p/FPS:.2f}", f"{(q+1)/FPS:.2f}"])
lens = np.array([q - p + 1 for p, q, *_ in found]) if found else np.array([0])
print(f"stage 1: {len(runs)} locally-linear runs (K={K}, blend>={BLEND_MIN}, minrun={MIN_RUN})")
print(f"stage 2: {len(found)} dissolves/fades (global blend>={GBLEND_MIN}, or >={WEAK_GBLEND} with "
      f"endpoint rms>={WEAK_EP}; alpha drop>={DROP_MIN}); "
      f"length median {np.median(lens):.0f} frames ({np.median(lens)/FPS:.2f}s), max {lens.max()}")
