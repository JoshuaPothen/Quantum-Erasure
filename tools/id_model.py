"""Identity classifier on CLIP crop embeddings (film/README step 5): L2-regularised logistic
regression in numpy, class-balanced. fit() / predict(); cv() prints 10-fold precision/recall."""
import csv
from pathlib import Path
import numpy as np
D = Path(__file__).resolve().parent.parent / "film" / "id"


def fit(X, y, lam=1e-3, it=3000, lr=0.5):
    Xb = np.hstack([X, np.ones((len(X), 1))])
    w = np.zeros(Xb.shape[1])
    cw = np.where(y == 1, 0.5 / max(1, y.mean()), 0.5 / max(1e-9, 1 - y.mean()))
    for _ in range(it):
        p = 1 / (1 + np.exp(-Xb @ w))
        g = Xb.T @ (cw * (p - y)) / len(y) + lam * np.r_[w[:-1], 0]
        w -= lr * g
    return w


def predict(w, X):
    return 1 / (1 + np.exp(-(np.hstack([X, np.ones((len(X), 1))]) @ w)))


def data():
    E = np.load(D / "emb.npy")
    L = [r for r in csv.DictReader(open(D / "labels.csv")) if int(r["label"]) >= 0 and int(r["id"]) < len(E)]
    ids = np.array([int(r["id"]) for r in L])
    return E[ids] * 10, np.array([int(r["label"]) for r in L]), ids


def cv(lam=1e-3, k=10, t=0.5):
    X, y, ids = data()
    rng = np.random.RandomState(0)
    fold = rng.randint(0, k, len(y))
    p = np.zeros(len(y))
    for f in range(k):
        w = fit(X[fold != f], y[fold != f], lam)
        p[fold == f] = predict(w, X[fold == f])
    pr = p > t
    tp, fp, fn = (pr & (y == 1)).sum(), (pr & (y == 0)).sum(), (~pr & (y == 1)).sum()
    print(f"lam {lam} t {t}: n {len(y)} acc {(pr == y).mean():.3f} precision {tp / max(1, tp + fp):.3f} "
          f"recall {tp / max(1, tp + fn):.3f}  (fp {fp}, fn {fn})")
    return p, y, ids


if __name__ == "__main__":
    for lam in (1e-4, 1e-3, 1e-2):
        cv(lam)
