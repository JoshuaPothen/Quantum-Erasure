#!/bin/bash
# exit when STATUS.csv has >= $1 non-absent rows beyond those in film/reviewed.txt, on ERRORS.txt, or when the run ends
cd "C:/All Github Code/AbInt/Quantum Erasure"
while true; do
  n=$(awk -F, 'NR>1 && $6!="absent"{print $1}' film/segments/STATUS.csv | sort -u | grep -vxFf <(cat film/reviewed.txt 2>/dev/null; echo none) | wc -l)
  [ "$n" -ge "$1" ] && { echo "present-unreviewed=$n"; tail -1 film/segments/STATUS.csv | cut -c1-80; exit 0; }
  [ -s film/segments/ERRORS.txt ] && { echo ERRORS; cat film/segments/ERRORS.txt; exit 0; }
  grep -q "seg1308 " film/segments/run.log && { echo RUN-END; exit 0; }
  sleep 60
done
