#!/bin/bash
set -euo pipefail

pull_request="$1"
head_sha="$2"
bottle_directory="$3"
script_directory="$(dirname "${BASH_SOURCE[0]}")"

# Apply the reviewed PR to current main without rewriting either branch's
# history. Fetching the PR ref also detects an update after approval validation.
git fetch origin main
git switch main
git merge --ff-only origin/main
git fetch origin "refs/pull/${pull_request}/head"
fetched_head="$(git rev-parse FETCH_HEAD)"
if [[ "${fetched_head}" != "${head_sha}" ]]
then
  echo 'error: Formula PR head changed after approval; start a new approval.' >&2
  exit 1
fi
git merge --squash FETCH_HEAD
python3 "${script_directory}/bottle_recipes.py" verify "${bottle_directory}"
git commit -m "Merge Formula pull request #${pull_request}" -m "Closes #${pull_request}."

# pr-upload consumes local JSON/tar files. pr-pull would download artifacts again
# by name and could substitute bytes that were never approved.
cd "${bottle_directory}"
brew pr-upload --debug
