"""Probe which image version directory exists on karsenal for one known card."""
import requests

card = "13e_dragons"
langs = ["zh-Hans", "zh-CN"]
for ver in range(45, 90):
    for lang in langs:
        url = f"https://karsenal.netlify.app/images/card/v{ver}/{lang}/{card}.avif"
        try:
            r = requests.head(url, timeout=8,
                              headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                print(f"FOUND {url}  ({r.headers.get('content-length')} bytes)")
        except Exception:
            pass
print("done probing")
