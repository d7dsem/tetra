#!/bin/bash
# Zips source-py/ into <repo>/bak/, excluding __pycache__.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p bak
out="bak/source-py-$(date +%Y-%m-%d_%H%M%S).zip"

zip -rq "$out" source-py -x '*/__pycache__/*'
echo "$out"
