#!/usr/bin/env bash
# Fetch the pinned MassBank Athens_Univ slice.
#
# The full MassBank-data repository is large, so this uses a blobless, sparse
# checkout of just the Athens_Univ contributor directory.  The commit is pinned
# so the curated manifest and the evaluation cannot silently drift.
set -euo pipefail

REPO_URL="https://github.com/MassBank/MassBank-data.git"
COMMIT="befc8a1e2f2aef899747797c081a5d80fab12fe7"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/data/raw/massbank"
EXPECTED_RECORDS=5633

if ! command -v git >/dev/null 2>&1; then
  echo "error: git is required" >&2
  exit 1
fi

if [ ! -d "${DEST}/.git" ]; then
  echo "==> cloning ${REPO_URL} (blobless, sparse)"
  mkdir -p "$(dirname "${DEST}")"
  git clone --filter=blob:none --no-checkout "${REPO_URL}" "${DEST}"
  git -C "${DEST}" sparse-checkout init --cone
fi

git -C "${DEST}" sparse-checkout set Athens_Univ

echo "==> checking out pinned commit ${COMMIT}"
git -C "${DEST}" fetch --filter=blob:none origin "${COMMIT}"
git -C "${DEST}" checkout --detach "${COMMIT}"

ACTUAL="$(git -C "${DEST}" rev-parse HEAD)"
if [ "${ACTUAL}" != "${COMMIT}" ]; then
  echo "error: HEAD ${ACTUAL} does not match pinned commit ${COMMIT}" >&2
  exit 1
fi

COUNT="$(find "${DEST}/Athens_Univ" -type f -name '*.txt' | wc -l | tr -d ' ')"
echo "==> ${COUNT} raw records in ${DEST}/Athens_Univ"
if [ "${COUNT}" != "${EXPECTED_RECORDS}" ]; then
  echo "warning: expected ${EXPECTED_RECORDS} records at this commit, found ${COUNT}" >&2
fi

echo "==> next: make prepare"
