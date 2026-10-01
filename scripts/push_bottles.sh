#!/bin/bash
set -euo pipefail
script_directory="$(dirname "${BASH_SOURCE[0]}")"
formula_paths="$1"
publication_base="$2"
hook_directory="$(mktemp -d)"
trap 'rm -rf "${hook_directory}"' EXIT
trap 'echo "error: Bottles were uploaded, but main was not updated. Inspect the failure before retrying publication." >&2' ERR

# Bind a normal push to the tip just checked. Git's push protocol then rejects
# changes after its ref advertisement, even when the PR already contains them.
cp "${script_directory}/check_push_tip.sh" "${hook_directory}/pre-push"
chmod +x "${hook_directory}/pre-push"

# Other PRs can advance main while bottles are being uploaded. Merge compatible
# changes without rewriting the approved publication commits or uploading again.
for _attempt in 1 2 3
do
  git fetch origin main
  python3 "${script_directory}/bottle_recipes.py" merge-main "${formula_paths}" "${publication_base}"
  checked_main="$(git rev-parse origin/main)"
  if CHECKED_MAIN_SHA="${checked_main}" git -c core.hooksPath="${hook_directory}" push origin main
  then
    exit 0
  fi
done
echo 'error: Bottles were uploaded, but main could not be updated. Inspect the failed push before retrying publication.' >&2
exit 1
