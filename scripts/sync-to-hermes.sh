#!/bin/bash
# sync-to-hermes.sh — Sync KAFED project to Hermes skills for testing
# Usage: ./scripts/sync-to-hermes.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SKILL_DEST="$HOME/.hermes/skills/meta/KAFED"

echo "Syncing KAFED from $SCRIPT_DIR to $SKILL_DEST"

# Sync src/
rsync -a --delete \
  --exclude='__pycache__' --exclude='*.pyc' \
  "$SCRIPT_DIR/src/" "$SKILL_DEST/src/"

# Sync config files
cp "$SCRIPT_DIR/pyproject.toml" "$SKILL_DEST/"
cp "$SCRIPT_DIR/README.md" "$SKILL_DEST/"

echo "Done. $SKILL_DEST updated."
