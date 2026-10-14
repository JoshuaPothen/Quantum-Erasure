"""Compare two encodes of the film on identical timestamps.
Metrics (per frame, on luma):
  blockiness  - mean |step| across 8px block boundaries / mean |step| elsewhere
                (1.0 = no block edges; higher = visible 8x8 grid)
  detail      - variance of Laplacian (fine line/texture energy)
  dark_noise  - std of high-pass in dark regions (V<70): mosquito/blotch noise
                in exactly the areas hair-vs-rock masking struggled with
"""
import subprocess, numpy as np, cv2, sys, os
FF = r"C:/Users/POTHEN/AppData/Local/autolumelive_colab/ffmpeg.exe"
A = ("YIFY", "Pocahontas.1995.1080p.BrRip.x264.YIFY.mp4")
B = ("BDrip", "Pocahontas (1995) BDrip 1080p ENG-ITA MultiSub x264 blyuray -Shiv@.mkv")
TIMES = [float(t) for t in sys.argv[1:]] or [300, 900, 1500, 2100, 2700, 3300, 3900, 4500]

def grab(path, t, h):
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8)[:1920*h*3].reshape(h, 1920, 3)

def blockiness(y):
    d = np.abs(np.diff(y.astype(np.float32), axis=1))
    cols = np.arange(d.shape[1])
    edge = d[:, cols % 8 == 7].mean(); other = d[:, cols % 8 != 7].mean()
    dv = np.abs(np.diff(y.astype(np.float32), axis=0)); rows = np.arange(dv.shape[0])
    edge_v = dv[rows % 8 == 7].mean(); other_v = dv[rows % 8 != 7].mean()
    return (edge / other + edge_v / other_v) / 2

def metrics(img):
    y = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 2]
    hp = y.astype(np.float32) - cv2.GaussianBlur(y, (0, 0), 2).astype(np.float32)
    dark = v < 70
    return blockiness(y), cv2.Laplacian(y, cv2.CV_32F).var(), (hp[dark].std() if dark.mean() > 0.02 else np.nan), dark.mean()

rows = []
for t in TIMES:
    a = grab(A[1], t, 1072); b = grab(B[1], t, 1080)
    # find vertical crop offset of YIFY inside BDrip, and check the frames match
    best = min(range(0, 9), key=lambda o: np.abs(b[o:o+1072].astype(np.int16) - a).mean())
    b = b[best:best+1072]
    diff = np.abs(b.astype(np.int16) - a).mean()
    ma, mb = metrics(a), metrics(b)
    rows.append((t, best, diff, ma, mb))
    cv2.imwrite(f"checks/src_compare/t{int(t)}_yify.png", a); cv2.imwrite(f"checks/src_compare/t{int(t)}_bdrip.png", b)
    print(f"t={t:6.0f}s off={best} meanAbsDiff={diff:5.1f} | blockiness Y={ma[0]:.3f} B={mb[0]:.3f} | "
          f"detail Y={ma[1]:7.1f} B={mb[1]:7.1f} | darkNoise Y={ma[2]:.2f} B={mb[2]:.2f} (dark {ma[3]*100:.0f}%)")
r = np.array([[x[3][0], x[4][0], x[3][1], x[4][1]] for x in rows])
print(f"MEAN blockiness YIFY={r[:,0].mean():.3f} BDrip={r[:,1].mean():.3f} | detail YIFY={r[:,2].mean():.1f} BDrip={r[:,3].mean():.1f}")
