#!/usr/bin/env bash
set -euo pipefail

revision="abbae723028d71be674e71e1a71201a6f43fab22"
model_file="Ternary-Bonsai-27B-Q2_0.gguf"
model_sha256="868c11714cf8fe47f5ec9eeb2be0ab1a337112886f92ee0ede6b855c4fa31757"
model_size=7165121600
repo_url="https://huggingface.co/prism-ml/Ternary-Bonsai-27B-gguf/resolve/${revision}"
target_dir="${1:?usage: bonsai-ternary-download TARGET_DIR}"
manifest="${target_dir}/.bonsai-manifest.json"
model_path="${target_dir}/${model_file}"

mkdir -p "$target_dir"

if [[ -f "$model_path" && -f "$manifest" ]] \
  && [[ "$(stat -c %s "$model_path")" == "$model_size" ]] \
  && jq -e \
    --arg revision "$revision" \
    --arg sha256 "$model_sha256" \
    --argjson size "$model_size" \
    '.revision == $revision and .sha256 == $sha256 and .size == $size' \
    "$manifest" >/dev/null; then
  echo "Bonsai checkpoint already materialized and verified: $model_path"
  exit 0
fi

model_verified=false
if [[ -f "$model_path" && "$(stat -c %s "$model_path")" == "$model_size" ]]; then
  actual_sha256="$(sha256sum "$model_path" | cut -d ' ' -f 1)"
  if [[ "$actual_sha256" == "$model_sha256" ]]; then
    model_verified=true
  fi
fi

if [[ "$model_verified" == false ]]; then
  partial="${model_path}.part"
  curl \
    --fail \
    --location \
    --retry 8 \
    --retry-all-errors \
    --retry-delay 2 \
    --continue-at - \
    --output "$partial" \
    "${repo_url}/${model_file}"

  actual_size="$(stat -c %s "$partial")"
  if [[ "$actual_size" != "$model_size" ]]; then
    echo "checkpoint size mismatch: got $actual_size, expected $model_size" >&2
    exit 1
  fi

  actual_sha256="$(sha256sum "$partial" | cut -d ' ' -f 1)"
  if [[ "$actual_sha256" != "$model_sha256" ]]; then
    echo "checkpoint SHA-256 mismatch" >&2
    exit 1
  fi

  mv "$partial" "$model_path"
fi

download_notice() {
  local filename="$1"
  local expected_sha256="$2"
  local output="${target_dir}/${filename}"
  local temporary="${output}.part"
  curl --fail --location --retry 5 --retry-all-errors \
    --output "$temporary" "${repo_url}/${filename}"
  echo "${expected_sha256}  ${temporary}" | sha256sum --check --status
  mv "$temporary" "$output"
}

download_notice LICENSE.txt 69849221bfb90053de2134ef5e6d540287b4b98062326492f1f96f5da685524b
download_notice NOTICE.txt cef33f95425f9802de78b7b22db0faca84d2216661432a9afcf9620949c21f7e

manifest_tmp="${manifest}.part"
jq -n \
  --arg repository "prism-ml/Ternary-Bonsai-27B-gguf" \
  --arg revision "$revision" \
  --arg filename "$model_file" \
  --arg sha256 "$model_sha256" \
  --argjson size "$model_size" \
  '{repository: $repository, revision: $revision, filename: $filename, sha256: $sha256, size: $size}' \
  >"$manifest_tmp"
mv "$manifest_tmp" "$manifest"

echo "Bonsai checkpoint materialized and verified: $model_path"
