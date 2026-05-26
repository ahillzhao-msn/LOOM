#!/usr/bin/env bash
# KAFED One-click install (legacy → bootstrap wrapper)
# Delegates to the new automated bootstrap

set -euo pipefail
cd "$(dirname "$0")"
echo "== KAFED Setup (bootstrap) =="
echo "Delegating to new kafed-bootstrap..."
echo ""
exec bash scripts/kafed-bootstrap.sh "$@"
