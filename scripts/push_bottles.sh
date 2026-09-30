#!/bin/bash
set -euo pipefail

# Other PRs can advance main while bottles are being uploaded. Merge compatible
# changes without rewriting the approved publication commits or uploading again.
for attempt in 1 2 3
do
  if git push origin main
  then
    exit 0
  fi
  if [[ "${attempt}" != 3 ]]
  then
    git fetch origin main
    git merge --no-edit origin/main
  fi
done
echo 'error: Bottles were uploaded, but main could not be updated. Inspect the failed push before retrying publication.' >&2
exit 1
