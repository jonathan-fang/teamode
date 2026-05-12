#!/bin/bash

if [ -f "$HOME/.bashrc" ]; then
    # shellcheck source=/dev/null
    source "$HOME/.bashrc"
fi

# TeaMode Launcher
# Requires ~/.teamode-secrets with DISCORD_BOT_TOKEN set.
# Optional env vars (set in .bashrc or ~/.teamode-secrets):
#   TEAMODE_DB_PATH     — SQLite DB path (default: ./sessions.db)
#   TEAMODE_REPO        — path to repo root; defaults to script's parent directory
#   TEAMODE_STABLE_PATH — path to stable worktree; defaults to ../teamode-stable

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${TEAMODE_REPO:-$(dirname "$SCRIPT_DIR")}"

if [ -f "$HOME/.teamode-secrets" ]; then
    # shellcheck source=/dev/null
    source "$HOME/.teamode-secrets"
else
    echo "Error: ~/.teamode-secrets not found. Create it with DISCORD_BOT_TOKEN set."
    exit 1
fi

if [ -z "$DISCORD_BOT_TOKEN" ]; then
    echo "Error: DISCORD_BOT_TOKEN is not set. Check ~/.teamode-secrets."
    exit 1
fi

STABLE_PATH="${TEAMODE_STABLE_PATH:-$(dirname "$REPO")/teamode-stable}"

MODE="${1:-dev}"

case "$MODE" in
stable)
    if [ ! -d "$STABLE_PATH" ]; then
        echo "Error: stable worktree not found at $STABLE_PATH"
        echo "Run: git worktree add $STABLE_PATH stable"
        exit 1
    fi
    cd "$STABLE_PATH" || exit 1
    # shellcheck source=/dev/null
    source "$REPO/.venv/bin/activate"
    python3 teamode.py
    ;;
dev | "")
    cd "$REPO" || exit 1
    # shellcheck source=/dev/null
    source "$REPO/.venv/bin/activate"
    python3 teamode.py
    ;;
*)
    echo "Usage: $(basename "$0") [dev|stable]"
    exit 1
    ;;
esac
