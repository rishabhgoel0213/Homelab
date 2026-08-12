#!/usr/bin/env bash
set -euo pipefail

repository="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
revision="b14872a58afd94e2fbbc1e5a1fe4ebb7dfdc5fdd"
expected_shards=52
expected_shard_bytes=21561882284
target_dir="${1:?usage: nemotron-lightning-download TARGET_DIR}"
manifest="${target_dir}/.nemotron-lightning-manifest.json"

checkpoint_complete() {
  local -a shards
  local total=0

  shopt -s nullglob
  shards=("${target_dir}"/model-*-of-*.safetensors)
  shopt -u nullglob
  if [[ "${#shards[@]}" -ne "$expected_shards" ]]; then
    return 1
  fi
  for shard in "${shards[@]}"; do
    total=$((total + $(stat -c %s "$shard")))
  done
  [[ "$total" -eq "$expected_shard_bytes" ]]
}

mkdir -p "$target_dir"

if [[ -f "$manifest" ]] \
  && jq -e --arg repository "$repository" --arg revision "$revision" \
    '.repository == $repository and .revision == $revision' "$manifest" >/dev/null \
  && checkpoint_complete; then
  echo "Nemotron checkpoint already materialized and verified: $target_dir"
  exit 0
fi

export HF_HUB_DISABLE_TELEMETRY=1
export HF_HUB_DISABLE_PROGRESS_BARS=0
hf download "$repository" \
  --revision "$revision" \
  --local-dir "$target_dir"

if ! checkpoint_complete; then
  echo "Nemotron checkpoint shard count or aggregate size mismatch" >&2
  exit 1
fi

manifest_tmp="${manifest}.part"
jq -n \
  --arg repository "$repository" \
  --arg revision "$revision" \
  --argjson shards "$expected_shards" \
  --argjson shardBytes "$expected_shard_bytes" \
  '{repository: $repository, revision: $revision, shards: $shards, shardBytes: $shardBytes}' \
  >"$manifest_tmp"
mv "$manifest_tmp" "$manifest"

echo "Nemotron checkpoint materialized and verified: $target_dir"
