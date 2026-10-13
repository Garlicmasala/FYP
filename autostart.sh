#!/usr/bin/env bash
# NexusHub autostart — run on every shell/session open.
# Idempotent: only starts backend(8000) and frontend(8010) if not already listening,
# so it is safe to run from ~/.bashrc / ~/.profile every login.
# Sandbox note: this VM reaps background processes when idle; re-run this (or ./run.sh)
# to revive. Public tunnels are not persisted by this sandbox.
ROOT="/home/user/Doubao/chats/38446483657218818/nexushub"
LOG="$ROOT/.logs"; mkdir -p "$LOG"

is_listening() { ss -ltn 2>/dev/null | grep -q ":$1 "; }

if ! is_listening 8000; then
  ( cd "$ROOT/backend" && nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 > "$LOG/backend.log" 2>&1 & )
fi
if ! is_listening 8010; then
  ( cd "$ROOT/barebone" && nohup python3 -m http.server 8010 --bind 0.0.0.0 > "$LOG/frontend.log" 2>&1 & )
fi
