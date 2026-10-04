#!/usr/bin/env bash
# Run all campus tests on the dedicated test site. Usage: scripts/test.sh [extra run-tests args]
set -euo pipefail

TEST_SITE="campus-test.localhost"
for arg in "$@"; do
	if [[ "$arg" == "--site" || "$arg" == --site=* ]]; then
		echo "scripts/test.sh only runs on $TEST_SITE; do not pass --site." >&2
		exit 1
	fi
done

BENCH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$BENCH_ROOT"
exec bench --site "$TEST_SITE" run-tests --app campus "$@"
