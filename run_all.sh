#!/usr/bin/env bash
# Launch the full Quell demo locally: ShopWave (the monitored app) and the
# Quell operator dashboard. Loads .env if present.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] && set -a && . ./.env && set +a

echo "starting ShopWave on http://localhost:8080"
( cd shopwave && node server.js ) &
SHOP_PID=$!

echo "starting Quell dashboard on http://localhost:8090"
( cd dashboard && python3 server.py ) &
DASH_PID=$!

trap 'kill $SHOP_PID $DASH_PID 2>/dev/null || true' EXIT
echo
echo "  ShopWave store   : http://localhost:8080   (use the Chaos Panel)"
echo "  Quell console : http://localhost:8090   (detect & prevent)"
echo "  generate traffic : (cd shopwave && node traffic.js)"
echo
wait
