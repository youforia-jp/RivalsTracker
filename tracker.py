import csv
import random
import time
import urllib.parse
import cloudscraper

# ── Hero → Role mapping ───────────────────────────────────────────────────────
# tracker.gg sometimes uses shortened hero names; both variants are listed.
# Multi-Role heroes appear in the detail section but are excluded from the
# role WR summary since they don't cleanly belong to one class.
HERO_ROLES = {
    # ── Launch roster ─────────────────────────────────────────────────────────
    # Vanguards
    'Thor':              'Vanguard',
    'Captain America':   'Vanguard',
    'Doctor Strange':    'Vanguard',
    'Hulk':              'Vanguard',
    'Magneto':           'Vanguard',
    'Venom':             'Vanguard',
    'Peni Parker':       'Vanguard',
    'Groot':             'Vanguard',
    'Captain Marvel':    'Vanguard',
    # Duelists
    'Black Panther':     'Duelist',
    'Hawkeye':           'Duelist',
    'Hela':              'Duelist',
    'Iron Man':          'Duelist',
    'Magik':             'Duelist',
    'Storm':             'Duelist',
    'Psylocke':          'Duelist',
    'Spider-Man':        'Duelist',
    'Black Widow':       'Duelist',
    'Moon Knight':       'Duelist',
    'Namor':             'Duelist',
    'Scarlet Witch':     'Duelist',
    'Winter Soldier':    'Duelist',
    'Wolverine':         'Duelist',
    'Iron Fist':         'Duelist',
    'Squirrel Girl':     'Duelist',
    'Star-Lord':         'Duelist',
    'Punisher':          'Duelist',
    # Strategists
    'Luna Snow':             'Strategist',
    'Mantis':                'Strategist',
    'Jeff the Land Shark':   'Strategist',   # API sometimes returns lowercase 't'
    'Jeff The Land Shark':   'Strategist',   # API actual casing
    'Jeff':                  'Strategist',   # short name fallback
    'Adam Warlock':          'Strategist',
    'Rocket Raccoon':        'Strategist',
    'Cloak & Dagger':        'Strategist',
    'Loki':                  'Strategist',
    # ── Season 1 ──────────────────────────────────────────────────────────────
    'Mister Fantastic':  'Duelist',
    'Mr. Fantastic':     'Duelist',          # alternate name fallback
    'Invisible Woman':   'Strategist',
    'Human Torch':       'Duelist',
    'The Thing':         'Vanguard',
    # ── Season 2 ──────────────────────────────────────────────────────────────
    'Emma Frost':        'Vanguard',
    'Ultron':            'Strategist',
    # ── Season 3 ──────────────────────────────────────────────────────────────
    'Phoenix':           'Duelist',
    'Blade':             'Duelist',
    # ── Season 4 ──────────────────────────────────────────────────────────────
    'Angela':            'Vanguard',
    'Daredevil':         'Duelist',
    # ── Season 5 ──────────────────────────────────────────────────────────────
    'Gambit':            'Strategist',
    'Rogue':             'Vanguard',
    # ── Season 6 ──────────────────────────────────────────────────────────────
    'Deadpool':          'Multi-Role',       # can play Vanguard / Duelist / Strategist
    'Elsa Bloodstone':   'Duelist',
    # ── Season 7 (current) ────────────────────────────────────────────────────
    'White Fox':         'Strategist',
}

TOP_N            = 5    # top heroes shown in the hero breakdown section
RATE_LIMIT_SLEEP = 12   # base seconds between requests (tracker.gg is strict)
RATELIMIT_JITTER = 5    # random extra seconds added to each delay (looks human)
RETRY_WAIT       = 60   # seconds to wait after a 429 before retrying
MAX_RETRIES      = 3    # maximum 429 retries per player

# Realistic browser headers — reduces chance of being fingerprinted as a bot
BROWSER_HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/123.0.0.0 Safari/537.36',
    'Accept':          'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate',
    'Referer':         'https://tracker.gg/marvel-rivals',
    'Origin':          'https://tracker.gg',
    'DNT':             '1',
    'Connection':      'keep-alive',
}


def load_igns(input_file):
    """Read a single-column CSV of IGNs (header row = 'IGN')."""
    igns = []
    with open(input_file, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        try:
            next(reader)  # skip header row
        except StopIteration:
            print(f"⚠️  {input_file} is empty. Add 'IGN' as the first line, then one player IGN per line below it.")
            return []
        for row in reader:
            if row and row[0].strip():
                igns.append(row[0].strip())
    if not igns:
        print(f"⚠️  No IGNs found in {input_file}. Add player names below the 'IGN' header.")
    return igns


def parse_wr(display_value):
    """Convert '61.3%' → 0.613. Returns None on failure."""
    try:
        return float(str(display_value).strip('%')) / 100
    except (ValueError, TypeError):
        return None


def make_scraper():
    """Create a fresh cloudscraper session with realistic browser headers.
    A new session per player prevents a blocked session from cascading."""
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
    )
    scraper.headers.update(BROWSER_HEADERS)
    return scraper


def is_valid_json(text):
    """Return True if text can be parsed as JSON."""
    import json
    try:
        json.loads(text)
        return True
    except Exception:
        return False


def safe_json(response):
    """Parse JSON from a response with a helpful error if the body is bad."""
    import json
    text = (response.text or '').strip()
    try:
        return json.loads(text)
    except Exception as exc:
        preview = text[:300] if text else '(empty)'
        print(f"  Bad response body (first 300 chars): {preview!r}")
        raise ValueError(f"Non-JSON response from tracker.gg: {exc}")


def fetch_with_retry(url):
    """Create a fresh session and GET url, retrying on 429 or any non-JSON 200."""
    for attempt in range(MAX_RETRIES):
        scraper  = make_scraper()
        response = scraper.get(url)

        # Hard rate-limit
        if response.status_code == 429:
            wait = RETRY_WAIT * (attempt + 1)
            print(f"  Rate limited (429) — waiting {wait}s before retry {attempt + 1}/{MAX_RETRIES}...")
            time.sleep(wait)
            continue

        # For 200s, validate the body is actually JSON before returning.
        # Cloudflare can return HTML or JS challenge pages with status 200.
        if response.status_code == 200:
            text = (response.text or '').strip()
            if not is_valid_json(text):
                preview = text[:150] if text else '(empty)'
                wait = RETRY_WAIT * (attempt + 1)
                print(f"  Non-JSON 200 response (preview: {preview!r})")
                print(f"  Waiting {wait}s before retry {attempt + 1}/{MAX_RETRIES}...")
                time.sleep(wait)
                continue

        return response

    return response  # return last response after exhausting retries



def pull_draft_stats(igns, output_file):
    """
    Fetches tracker.gg data for every IGN and writes THREE sections to the CSV:

    SECTION 1 — Player Overview (one row per player)
      IGN | Main_Role | Overall_KDA | Overall_WinRate% | Total_Matches | Status

    SECTION 2 — Hero Breakdown (one row per player × top-N hero)
      IGN | Hero_Rank | Hero | Role | KDA | WinRate% | Matches | Status

    SECTION 3 — Role Win Rate Summary (one row per player × role)
      IGN | Role | Weighted_WinRate% | Role_Matches | Status

    Overall KDA/WR come from the overview segment (segments[0]).
    Main_Role is whichever of Vanguard / Duelist / Strategist has the most
    matches across all heroes played.
    Role WR is a match-weighted average so heavy hitters outweigh warm-up games.
    """
    all_players = []

    for ign in igns:
        if not ign:
            continue

        safe_ign = urllib.parse.quote(ign)
        print(f"Fetching stats for {ign}...")
        url = (
            f"https://api.tracker.gg/api/v2/marvel-rivals/standard/"
            f"profile/ign/{safe_ign}"
        )

        try:
            response = fetch_with_retry(url)

            if response.status_code == 200:
                data     = safe_json(response)
                segments = data['data']['segments']

                # ── Overview stats (segment[0]) ───────────────────────────────
                overview        = segments[0]['stats']
                overall_kda     = overview.get('kdaRatio',      {}).get('displayValue', 'N/A')
                overall_wr      = overview.get('matchesWinPct', {}).get('displayValue', 'N/A')
                overall_matches = overview.get('matchesPlayed', {}).get('displayValue', 'N/A')
                current_rank      = overview.get('ranked',     {}).get('metadata', {}).get('tierName', 'N/A')
                season_peak_rank  = overview.get('peakRanked', {}).get('metadata', {}).get('tierName', 'N/A')

                # ── Hero segments — sorted most-played first ───────────────────
                hero_segs = sorted(
                    [s for s in segments if s.get('type') == 'hero'],
                    key=lambda s: s['stats'].get('matchesPlayed', {}).get('value', 0),
                    reverse=True,
                )

                heroes     = []
                role_stats = {
                    r: {'weighted_wr_sum': 0.0, 'matches': 0}
                    for r in ('Vanguard', 'Duelist', 'Strategist')
                }

                for seg in hero_segs:
                    hero_name   = seg['metadata'].get('name', 'Unknown')
                    stats       = seg['stats']
                    kda         = stats.get('kdaRatio',      {}).get('displayValue', 'N/A')
                    wr_raw      = stats.get('matchesWinPct', {}).get('displayValue', 'N/A')
                    matches_val = stats.get('matchesPlayed', {}).get('value', 0)

                    try:
                        matches_int = int(matches_val)
                    except (ValueError, TypeError):
                        matches_int = 0

                    role = HERO_ROLES.get(hero_name, 'Unknown')
                    heroes.append({
                        'name': hero_name, 'role': role,
                        'kda': kda, 'wr': wr_raw, 'matches': matches_int,
                    })

                    # Accumulate role WR (skip Multi-Role / Unknown)
                    wr_float = parse_wr(wr_raw)
                    if role in role_stats and wr_float is not None and matches_int > 0:
                        role_stats[role]['weighted_wr_sum'] += wr_float * matches_int
                        role_stats[role]['matches']         += matches_int

                # Main role = role bucket with the most matches
                main_role = max(
                    ('Vanguard', 'Duelist', 'Strategist'),
                    key=lambda r: role_stats[r]['matches'],
                )
                if role_stats[main_role]['matches'] == 0:
                    main_role = 'Unknown'

                all_players.append({
                    'ign':            ign,
                    'main_role':      main_role,
                    'overall_kda':    overall_kda,
                    'overall_wr':     overall_wr,
                    'overall_matches':overall_matches,
                    'current_rank':      current_rank,
                    'season_peak_rank':  season_peak_rank,
                    'heroes':         heroes,
                    'role_stats':     role_stats,
                    'status':         'Success',
                })

            elif response.status_code == 404:
                all_players.append({
                    'ign': ign, 'main_role': 'N/A',
                    'overall_kda': 'N/A', 'overall_wr': 'N/A', 'overall_matches': 0,
                    'current_rank': 'N/A', 'season_peak_rank': 'N/A',
                    'heroes': [], 'role_stats': {}, 'status': 'Private/Not Found',
                })
            else:
                all_players.append({
                    'ign': ign, 'main_role': 'N/A',
                    'overall_kda': 'N/A', 'overall_wr': 'N/A', 'overall_matches': 0,
                    'current_rank': 'N/A', 'season_peak_rank': 'N/A',
                    'heroes': [], 'role_stats': {}, 'status': f'Error: {response.status_code}',
                })

        except Exception as e:
            all_players.append({
                'ign': ign, 'main_role': 'N/A',
                'overall_kda': 'N/A', 'overall_wr': 'N/A', 'overall_matches': 0,
                'current_rank': 'N/A', 'season_peak_rank': 'N/A',
                'heroes': [], 'role_stats': {}, 'status': f'Failed: {e}',
            })

        delay = RATE_LIMIT_SLEEP + random.uniform(0, RATELIMIT_JITTER)
        print(f"  Waiting {delay:.1f}s before next request...")
        time.sleep(delay)

    # ── Write the CSV ─────────────────────────────────────────────────────────
    with open(output_file, mode='w', newline='', encoding='utf-8') as outfile:
        writer = csv.writer(outfile)

        # ── Section 1: Player Overview ────────────────────────────────────────
        writer.writerow(['=== PLAYER OVERVIEW ==='])
        writer.writerow(['IGN', 'Main_Role', 'Current_Rank', 'Season_Peak_Rank', 'Overall_KDA', 'Overall_WinRate%', 'Total_Matches', 'Status'])
        for p in all_players:
            writer.writerow([
                p['ign'], p['main_role'],
                p['current_rank'], p['season_peak_rank'],
                p['overall_kda'], p['overall_wr'], p['overall_matches'],
                p['status'],
            ])

        # ── Section 2: Hero Breakdown ─────────────────────────────────────────
        writer.writerow([])
        writer.writerow(['=== HERO BREAKDOWN ==='])
        writer.writerow(['IGN', 'Hero_Rank', 'Hero', 'Role', 'KDA', 'WinRate%', 'Matches', 'Status'])
        for p in all_players:
            if not p['heroes']:
                writer.writerow([p['ign'], 'N/A', 'N/A', 'N/A', 'N/A', 'N/A', 0, p['status']])
                continue
            for rank, h in enumerate(p['heroes'][:TOP_N], start=1):
                writer.writerow([
                    p['ign'], rank, h['name'], h['role'],
                    h['kda'], h['wr'], h['matches'], p['status'],
                ])

        # ── Section 3: Role Win Rate Summary ──────────────────────────────────
        writer.writerow([])
        writer.writerow(['=== ROLE WIN RATE SUMMARY ==='])
        writer.writerow(['IGN', 'Role', 'Weighted_WinRate%', 'Role_Matches', 'Status'])
        for p in all_players:
            for role in ('Vanguard', 'Duelist', 'Strategist'):
                rs     = p.get('role_stats', {}).get(role, {'weighted_wr_sum': 0, 'matches': 0})
                avg_wr = (
                    f"{rs['weighted_wr_sum'] / rs['matches'] * 100:.1f}%"
                    if rs['matches'] > 0 else 'N/A'
                )
                writer.writerow([p['ign'], role, avg_wr, rs['matches'], p['status']])


if __name__ == "__main__":
    import os
    input_file = 'Master_IGNs.csv' if os.path.exists('Master_IGNs.csv') else 'IGNs.csv'
    print(f"Using input file: {input_file}")
    igns = load_igns(input_file)
    pull_draft_stats(igns, 'IGN_stats.csv')
    print("Done! Check IGN_stats.csv")