import cv2, sys
src, dst = sys.argv[1], sys.argv[2]
im = cv2.imread(src)
h, w = im.shape[:2]
for x in range(0, w, 100):
    cv2.line(im, (x, 0), (x, h), (0, 255, 0) if x % 500 else (0, 0, 255), 1)
    cv2.putText(im, str(x), (x + 2, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
for y in range(0, h, 100):
    cv2.line(im, (0, y), (w, y), (0, 255, 0) if y % 500 else (0, 0, 255), 1)
    cv2.putText(im, str(y), (2, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
cv2.imwrite(dst, im)
