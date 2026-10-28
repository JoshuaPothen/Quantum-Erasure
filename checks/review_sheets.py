"""Stack the QC sheets of finished segments with her hair present, 6 per image, for review
(film/README step 8). Already-reviewed segs are listed in film/reviewed.txt.
Usage: python checks/review_sheets.py [--all]  -> film/review/review_<k>.jpg"""
import csv, sys
from pathlib import Path
import cv2, numpy as np
R = Path(__file__).resolve().parent.parent / "film"
done = set((R / "reviewed.txt").read_text().split()) if (R / "reviewed.txt").exists() else set()
rows = {}
for r in csv.DictReader(open(R / "segments" / "STATUS.csv")):
    rows[r["seg"]] = r            # last row wins (reruns)
todo = [s for s, r in rows.items() if (r["status"] != "absent" or "--all" in sys.argv) and s not in done]
(R / "review").mkdir(exist_ok=True)
for k in range(0, len(todo), 6):
    ims = [cv2.resize(cv2.imread(str(R / "segments" / f"seg{int(s):04d}" / "sheet.jpg")), (1536, 236)) for s in todo[k:k + 6]]
    cv2.imwrite(str(R / "review" / f"review_{k // 6:03d}.jpg"), np.vstack(ims), [cv2.IMWRITE_JPEG_QUALITY, 85])
print(len(todo), "segments to review:", " ".join(todo))
