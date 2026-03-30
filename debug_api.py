import json
import urllib.parse
import cloudscraper

# ── Config ────────────────────────────────────────────────────────────────────
# Set this to any known-public IGN to inspect what the API actually returns.
ign = "PupusaEater26"

# ── Fetch ─────────────────────────────────────────────────────────────────────
scraper   = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
)
scraper.headers.update({
    'Accept':          'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate',
    'Referer':         'https://tracker.gg/marvel-rivals',
    'Origin':          'https://tracker.gg',
})

safe_ign = urllib.parse.quote(ign)
url      = f"https://api.tracker.gg/api/v2/marvel-rivals/standard/profile/ign/{safe_ign}"

response = scraper.get(url)
print(f"HTTP {response.status_code}")

data     = response.json()
segments = data['data']['segments']

# ── Overview segment (segments[0]) — dump EVERYTHING ─────────────────────────
print("\n" + "="*60)
print("OVERVIEW SEGMENT — segments[0]")
print("="*60)

overview_seg = segments[0]
print(f"\n--- metadata ---")
print(json.dumps(overview_seg.get('metadata', {}), indent=2))

print(f"\n--- stats keys and their values ---")
for key, val in overview_seg.get('stats', {}).items():
    display = val.get('displayValue', '?')
    raw     = val.get('value', '?')
    meta    = val.get('metadata', {})
    print(f"  {key!r:35} displayValue={display!r:20} value={raw!r:15} metadata={meta}")

# ── Hero segments — quick summary ─────────────────────────────────────────────
print("\n" + "="*60)
print(f"HERO SEGMENTS ({len([s for s in segments if s.get('type')=='hero'])} total)")
print("="*60)
for i, seg in enumerate(segments):
    if seg.get('type') != 'hero':
        continue
    name    = seg['metadata'].get('name', '?')
    matches = seg['stats'].get('matchesPlayed', {}).get('value', '?')
    print(f"  [{i}] {name} — {matches} matches")
