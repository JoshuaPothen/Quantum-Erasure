"""Append labels: python checks/add_labels.py <sheet> "<ids that are her>" "<unsure ids>"; the other ids on the sheet are 0."""
import csv, sys
from pathlib import Path
D = Path(__file__).resolve().parent.parent / "film" / "id"
if sys.argv[1] == "--ids":   # python checks/add_labels.py --ids <file> <k> "<her>" "<unsure>"
    ids_all = [int(x) for x in open(sys.argv[2]).read().split()]
    k = int(sys.argv[3])
    sheet_ids = ids_all[k * 40:(k + 1) * 40]
    sys.argv = sys.argv[2:]
else:
    k = int(sys.argv[1])
    sheet_ids = range(k * 40, k * 40 + 40)
yes = {int(x) for x in sys.argv[2].split()}
uns = {int(x) for x in sys.argv[3].split()} if len(sys.argv) > 3 else set()
p = D / "labels.csv"
old = {int(r["id"]): r for r in csv.DictReader(open(p))} if p.exists() else {}
for i in sheet_ids:
    old[i] = {"id": i, "label": 1 if i in yes else (-1 if i in uns else 0), "sheet": k}
with open(p, "w", newline="") as f:
    w = csv.DictWriter(f, ["id", "label", "sheet"])
    w.writeheader()
    w.writerows(old[i] for i in sorted(old))
print(len(old), "labelled;", sum(1 for r in old.values() if int(r["label"]) == 1), "positive")
