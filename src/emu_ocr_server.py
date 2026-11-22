"""Token-authenticated, loopback-only OCR shared by emulator workers.

Injected ocr_fn returns normalized (xyxy, text, score) items, like EmuVision.
RapidOCR is loaded lazily on the first request, under the inference lock.
"""
from __future__ import annotations

import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import sys
import threading
from urllib.parse import urlsplit

import cv2
import numpy as np

MAX_BODY = 8 * 1024 * 1024


def localhost_connection(url, timeout=10.0):
    """Use a direct socket, never the system's HTTP proxy configuration."""
    address = urlsplit(url)
    if (address.scheme != "http" or address.hostname != "127.0.0.1"
            or address.username is not None or address.password is not None
            or address.path not in ("", "/") or address.query or address.fragment
            or address.port is None):
        raise ValueError("OCR URL must be http://127.0.0.1:<port>")
    return http.client.HTTPConnection("127.0.0.1", address.port, timeout=timeout)


def request_ocr(url, token, frame, timeout=10.0) -> list:
    encoded, png = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not encoded:
        raise ValueError("Could not encode OCR frame")
    connection = localhost_connection(url, timeout)
    try:
        connection.request("POST", "/ocr", body=png.tobytes(),
                           headers={"X-OCR-Token": token, "Content-Type": "image/png"})
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise OSError(f"Shared OCR returned HTTP {response.status}")
        data = json.loads(body)
        if not data.get("ok") or not isinstance(data.get("items"), list):
            raise ValueError("Invalid shared OCR response")
        return data["items"]
    finally:
        connection.close()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # stdout is reserved for the CLI ready handshake.

    def _reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        supplied = self.headers.get("X-OCR-Token", "")
        if not secrets.compare_digest(supplied.encode("utf-8"), self.server.token.encode("utf-8")):
            self._reply(403, {"ok": False, "error": "Forbidden"})
            return False
        return True

    def do_GET(self):
        if not self._authorized():
            return
        if self.path != "/health":
            self._reply(404, {"ok": False})
            return
        self._reply(200, {"ok": True, "calls": self.server.calls})

    def do_POST(self):
        if not self._authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._reply(400, {"ok": False, "error": "Invalid Content-Length"})
            return
        if length > MAX_BODY:
            self._reply(413, {"ok": False, "error": "Body too large"})
            return
        if length < 0 or self.headers.get("Transfer-Encoding"):
            self._reply(400, {"ok": False, "error": "Invalid body framing"})
            return
        if self.path == "/shutdown":
            self._reply(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path != "/ocr":
            self._reply(404, {"ok": False})
            return
        self.connection.settimeout(10.0)
        try:
            body = self.rfile.read(length)
            frame = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR) if body else None
            if len(body) != length or frame is None:
                self._reply(400, {"ok": False, "error": "Invalid image"})
                return
        except (OSError, cv2.error):
            self._reply(400, {"ok": False, "error": "Invalid image"})
            return
        try:
            with self.server.ocr_lock:
                items = self.server.infer(frame)
                self.server.calls += 1
            self._reply(200, {"ok": True, "items": items})
        except Exception:
            self._reply(500, {"ok": False, "error": "OCR inference failed"})


class SharedOcrServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host="127.0.0.1", port=0, token=None, ocr_fn=None, ocr_threads=2):
        if host != "127.0.0.1":
            raise ValueError("Shared OCR must bind 127.0.0.1")
        self.token = token or os.environ.get("KARDS_EMU_OCR_TOKEN") or secrets.token_urlsafe(24)
        self.ocr_fn, self.ocr_threads = ocr_fn, ocr_threads
        self._ocr = None
        self.ocr_lock = threading.Lock()
        self.calls = 0
        self._thread = None
        super().__init__((host, port), _Handler)
        self.url = f"http://127.0.0.1:{self.server_port}"

    def infer(self, frame):
        if self.ocr_fn is not None:
            result = self.ocr_fn(frame)
        else:
            if self._ocr is None:
                from rapidocr_onnxruntime import RapidOCR
                self._ocr = RapidOCR(intra_op_num_threads=self.ocr_threads, inter_op_num_threads=1)
            raw, _ = self._ocr(frame)
            result = [([min(p[0] for p in box), min(p[1] for p in box),
                        max(p[0] for p in box), max(p[1] for p in box)], text, score)
                      for box, text, score in (raw or [])]
        return [[list(map(int, box)), str(text), float(score)] for box, text, score in result]

    def serve_forever(self, poll_interval=0.1):
        try:
            super().serve_forever(poll_interval=poll_interval)
        finally:
            self.server_close()

    def start_in_thread(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self.serve_forever, daemon=True)
            self._thread.start()
        return self._thread

    def stop(self):
        if self._thread is not None and self._thread.is_alive():
            self.shutdown()
            self._thread.join()
        self.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-threads", type=int, default=2)
    args = parser.parse_args()
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        if not kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00004000):
            print("Could not set OCR process priority to BelowNormal", file=sys.stderr)
    cv2.setNumThreads(2)
    server = SharedOcrServer(ocr_threads=args.ocr_threads)
    print(json.dumps({"ready": True, "url": server.url, "pid": os.getpid()}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
