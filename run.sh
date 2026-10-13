#!/usr/bin/env bash
# NexusHub one-shot runner + network deploy (Linux / cloud VM)
#   backend  : FastAPI on 0.0.0.0:8000
#   frontend : static white-theme page on 0.0.0.0:8010   (8080 is taken by the sandbox)
#   deploy   : public Cloudflare quick-tunnel for both   (needs outbound internet)
# Usage:
#   ./run.sh            start backend + frontend
#   ./run.sh -deploy    start backend + frontend + public tunnels
#   ./run.sh -fresh     reset ledgers (re-seed Garrick admin) first
# Note: this sandbox reaps background processes when idle — re-run ./run.sh to restart.
set -e
cd "$(dirname "$0")"
LOG="$PWD/.logs"; mkdir -p "$LOG"

if [ "$1" = "-fresh" ]; then
  echo "Resetting chain ledgers (re-seed Garrick admin)..."
  (cd backend && python3 reset_chains.py)
fi

echo "Starting backend on 0.0.0.0:8000 ..."
( cd backend && nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 > "$LOG/backend.log" 2>&1 & )
echo "Starting frontend on 0.0.0.0:8010 ..."
( cd barebone && nohup python3 -m http.server 8010 --bind 0.0.0.0 > "$LOG/frontend.log" 2>&1 & )

if [ "$1" = "-deploy" ] || [ "$2" = "-deploy" ]; then
  echo "Starting public tunnels (Cloudflare quick-tunnel)..."
  ( nohup "$HOME/bin/cloudflared" tunnel --no-autoupdate --url http://127.0.0.1:8000 > "$LOG/tunnel_backend.log" 2>&1 & )
  ( nohup "$HOME/bin/cloudflared" tunnel --no-autoupdate --url http://127.0.0.1:8010 > "$LOG/tunnel_frontend.log" 2>&1 & )
fi

sleep 3
echo
echo "NexusHub is running (local):"
echo "  Frontend : http://127.0.0.1:8010/"
echo "  Backend  : http://127.0.0.1:8000/docs"
echo "  Ledgers  : backend/chains/identity_chain.json (AWS)"
echo "             backend/chains/profile_chain.json  (Azure)"
echo "             backend/chains/content_chain.json  (GCP)"
echo "  Admin    : garrick@nexushub.dev / garrick123"
if [ "$1" = "-deploy" ] || [ "$2" = "-deploy" ]; then
  echo
  echo "Public URLs (wait ~15s for tunnels to register, then re-curl):"
  echo "  Frontend : $(grep -hoE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG"/tunnel_frontend.log 2>/dev/null | tail -1)"
  echo "  Backend  : $(grep -hoE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG"/tunnel_backend.log 2>/dev/null | tail -1)"
fi
