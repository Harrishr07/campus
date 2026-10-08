#!/usr/bin/env bash
# Run all campus tests on a dedicated test site. Usage: [CAMPUS_TEST_SITE=campus-test2.localhost] scripts/test.sh [extra run-tests args]
set -euo pipefail

TEST_SITE="${CAMPUS_TEST_SITE:-campus-test.localhost}"
if [[ ! "$TEST_SITE" =~ ^campus-test[0-9]*\.localhost$ ]]; then
	echo "CAMPUS_TEST_SITE must be campus-test.localhost, campus-test2.localhost or campus-test3.localhost." >&2
	exit 1
fi
for arg in "$@"; do
	if [[ "$arg" == "--site" || "$arg" == --site=* ]]; then
		echo "scripts/test.sh only runs on $TEST_SITE; do not pass --site." >&2
		exit 1
	fi
done

BENCH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$BENCH_ROOT"
exec bench --site "$TEST_SITE" run-tests --app campus "$@"
