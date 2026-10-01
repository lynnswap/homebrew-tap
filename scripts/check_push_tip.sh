#!/bin/bash
set -euo pipefail
checked_main="${CHECKED_MAIN_SHA:?Supply the verified main tip.}"
while read -r _local_ref _local_sha remote_ref remote_sha
do
  if [[ "${remote_ref}" == refs/heads/main && "${remote_sha}" != "${checked_main}" ]]
  then
    echo 'error: main changed after recipe verification; retrying with its current tip.' >&2
    exit 1
  fi
done
