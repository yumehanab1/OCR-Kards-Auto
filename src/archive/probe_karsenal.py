"""probe_karsenal.py - find real image URL version used by karsenal site."""
import re
import requests

URL = "https://karsenal.netlify.app/"
r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
html = r.text
print("status", r.status_code, "len", len(html))

patterns = {
    "ver assignment": r"ver\s*=\s*['\"]?([^;,'\"]{2,20})",
    "card/v dirs": r"card/v\d+",
    "imgUrl builder": r"/images/card/\$\{[^}]*\}/\$\{[^}]*\}/\$\{[^}]*\}",
    "lang/ver vars": r"(?:ver|imgVer|cardVer|lang)\s*[:=]\s*['\"][^'\"]+['\"]",
}
for name, pat in patterns.items():
    found = re.findall(pat, html)
    print(f"--- {name}: {len(found)} ---")
    for f in sorted(set(found))[:10]:
        print("  ", f)

# find any /images/... literal path
imgs = re.findall(r"/images/[A-Za-z0-9_./${}-]+", html)
print("--- image path literals:", len(set(imgs)), "---")
for i in sorted(set(imgs))[:15]:
    print("  ", i)
