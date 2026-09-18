"""Extract full JS logic around imgUrl to learn real image source."""
import re
import requests

r = requests.get("https://karsenal.netlify.app/", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
html = r.text

# find the JS block containing imgUrl builder and show surrounding context
idx = html.find("images/card/${ver}")
if idx >= 0:
    start = max(0, idx - 1500)
    end = min(len(html), idx + 800)
    print(html[start:end])
