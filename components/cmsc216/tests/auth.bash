#!/usr/bin/env bash

set -euo pipefail

cli="${1:?path to cmsc216 CLI is required}"
fake_ssh="${2:?path to fake SSH executable is required}"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT

mkdir -p "$test_root/home"

export HOME="$test_root/home"
export CMSC216_DIRECTORY_ID="test-user"
export CMSC216_LOCAL_ROOT="$test_root/course"
export CMSC216_REMOTE_ROOT="/home/test-user/216-sync"
export CMSC216_DATA_ROOT="$test_root/data"
export CMSC216_CODIUM_BIN="/bin/true"
export CMSC216_SSH_BIN="$fake_ssh"
export CMSC216_TEST_SSH_STATE="$test_root/master-active"

run_cli() {
  bash "$cli" "$@"
}

run_cli auth
run_cli auth-status | grep -Fq 'active:'
run_cli auth
run_cli auth-clear

if run_cli auth-status >/dev/null 2>&1; then
  printf 'auth-status unexpectedly succeeded without an active connection\n' >&2
  exit 1
fi
