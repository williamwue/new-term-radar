#!/usr/bin/env bash
# Free daily run for this fork: no paid AIsa, GoAnyAPI, or TrustMRR steps.
#
# Still runs:
#   ① X, when x_accounts.posts_file is set (a local JSON file; no AIsa call)
#   ① Hugging Face
#   ② GitHub breakouts
#   ③ sitemaps / directories
#   ④ Search Console, when gsc.site is set (your own token; otherwise the signal stays off)
#
# Skipped. The first eight are the list from before 0.6.0. The last four are the
# paid signals 0.6.0 added (or made daily):
#   newsites    ③ domains that already rank, and each new site's first words (AIsa)
#   review      ⑤ the later Trends check (AIsa)
#   judge       the name judge (AIsa). Terms are listed unsorted.
#   usecases    the keyword table, including the 0.6.0 readings: word age, markets,
#               page-one shape, the twelve months, your rank, the exact-match .com
#   revenue     ⑥ TrustMRR
#   asks        ⑦ Reddit / X / Stack Exchange / Freelancer, and AI answers (AIsa)
#   tutorials   ⚡ comments under tutorial videos (AIsa and GoAnyAPI)
#   sellers     ⑧ payment links, including Paddle, Dodo Payments and Waffo (AIsa)
#   builders    ⑧b sites just built with Lovable or v0, beehiiv newsletters (AIsa)
#   feeds       ⑨ just listed. Trending searches call AIsa every day; Google's new
#               pages and rising root words call AIsa / GoAnyAPI weekly. The free
#               lists in the same signal (Product Hunt, Show HN, OpenRouter, the
#               App Store, awesome lists) are skipped with them: one flag covers it.
#   money       ⑩ AdSense portfolios and new advertisers (GoAnyAPI)
#   sidelights  whois on the day's names, and the "alternative" / "pricing" tails
#               of paying products (AIsa)
#
# `history`, `keywords` and `pains` are separate commands and are not run.
# Extra arguments are passed through: ./run_free.sh --out report.md
# Point it at another config with RADAR_CONFIG=/path/to/config.json.
set -euo pipefail
cd "$(dirname "$0")"

CONFIG="${RADAR_CONFIG:-config.json}"
SKIP="newsites,review,judge,usecases,revenue,asks,tutorials,sellers,builders,feeds,money,sidelights"

# X calls AIsa unless posts_file is set. Without that file, leave X out.
if ! python3 - "$CONFIG" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    sys.exit(1)
raw = json.loads(path.read_text(encoding="utf-8"))
posts = ((raw.get("x_accounts") or {}).get("posts_file") or "")
sys.exit(0 if str(posts).strip() else 1)
PY
then
  SKIP="x,${SKIP}"
  echo "run_free: ${CONFIG} has no x_accounts.posts_file; skipping X so it does not call AIsa" >&2
fi

exec python3 -m radar daily --config "$CONFIG" --skip "$SKIP" "$@"
