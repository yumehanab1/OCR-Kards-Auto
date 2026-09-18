"""diag_cost.py - check whether cost badge OCR works inside a hover-diff region."""
import sys, time, cv2, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from win import capture_client_bgr, find_by_process, set_dpi_aware, set_window_client_size, client_to_screen
from actions import set_cursor
from hand_scanner_v2 import diff_bbox, SAFE_POINT, PROBE_Y
from hover_card_reader import _ocr

set_dpi_aware()
wins = find_by_process("kards")
hwnd = wins[0]["hwnd"]
set_window_client_size(hwnd, 1280, 720, 100, 100)
time.sleep(1)

sx, sy = client_to_screen(hwnd, *SAFE_POINT)
set_cursor(sx, sy)
time.sleep(0.5)
base = capture_client_bgr(hwnd)

input(">>> Hover a 1-cost hand card now, then press Enter... ")
time.sleep(0.6)
hover = capture_client_bgr(hwnd)
box = diff_bbox(base, hover)
print("diff:", box)
if box:
    bx, by, bw, bh = box
    region = hover[by:by+bh, bx:bx+bw]
    cv2.imwrite(r"C:\Users\31291\Desktop\kards-auto\shots\diag_cost_region.png", region)
    print("region saved:", region.shape)
    print("=== full OCR on region ===")
    for ln in sorted(_ocr(region), key=lambda l: (l["y"], l["x"])):
        print(f"  [{ln['x']:.0f},{ln['y']:.0f}] {ln['text']!r} conf={ln['conf']:.2f}")
else:
    print("no diff - panel did not appear?")
