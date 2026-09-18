"""diag_scan.py - step-by-step diff scan diagnostic."""
import sys, time, cv2, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from win import capture_client_bgr, find_by_process, set_dpi_aware, set_window_client_size, client_to_screen
from actions import set_cursor
from hand_scanner_v2 import diff_bbox, SAFE_POINT, PROBE_Y

set_dpi_aware()
wins = find_by_process("kards")
hwnd = wins[0]["hwnd"]
set_window_client_size(hwnd, 1280, 720, 100, 100)
time.sleep(1)

sx, sy = client_to_screen(hwnd, *SAFE_POINT)
set_cursor(sx, sy)
time.sleep(0.5)
base = capture_client_bgr(hwnd)
print("baseline mean:", round(float(base.mean()), 1))

os.makedirs(r"C:\Users\31291\Desktop\kards-auto\shots\diag", exist_ok=True)
for x in [380, 420, 460, 500, 540, 580, 620, 660, 700]:
    px, py = client_to_screen(hwnd, x, PROBE_Y)
    set_cursor(px, py)
    time.sleep(0.6)
    hover = capture_client_bgr(hwnd)
    box = diff_bbox(base, hover)
    print(f"x={x}: diff={'NONE' if box is None else box}")
    if box:
        bx, by, bw, bh = box
        cv2.imwrite(rf"C:\Users\31291\Desktop\kards-auto\shots\diag\x{x}.png",
                    hover[by:by+bh, bx:bx+bw])
    set_cursor(sx, sy)
    time.sleep(0.3)
print("done")
