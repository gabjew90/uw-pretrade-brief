#!/usr/bin/env bash
# Regenerate requirements.txt from uv state for Streamlit Cloud.
set -euo pipefail
uv export --no-hashes --no-dev --format requirements-txt -o requirements.txt
echo "Wrote requirements.txt"
