#!/usr/bin/env bash
set -euo pipefail

repository="Comfy-Org/Qwen-Image-2.1"
revision="ace0edeb3791a594ddfa36ed5f41a178a394e921"
license_repository="Qwen/Qwen-Image-2.1"
license_revision="790c92633540aa0cb11d9abf19eb46d861714758"
target_dir="${1:?usage: qwen-image-2.1-download TARGET_DIR}"
manifest="${target_dir}/.qwen-image-2.1-manifest.json"

if [[ "${QWEN_IMAGE_LICENSE_ACCEPTED:-}" != "qwen-research" ]]; then
  cat >&2 <<'EOF'
Qwen-Image 2.1 is licensed for non-commercial research or evaluation only.
Using or downloading the model constitutes acceptance of the Qwen Research
License Agreement. Set QWEN_IMAGE_LICENSE_ACCEPTED=qwen-research to acknowledge
the license after reviewing it at:
https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE
EOF
  exit 2
fi

declare -a files=(
  "diffusion_models/qwen_image_2.1_int8_convrot.safetensors|7256783064|cb74113cb03faecd79611b01fd7fd642f0aa60d6f0b95086abee214d75eaa57d"
  "text_encoders/qwen3vl_8b_int8_convrot.safetensors|9350798360|8bfd0f6e12abf2d2d697ecc888e5e90b0d6741d6708f05799f53afa560452e8f"
  "vae/qwen_image_2.1_vae_bf16.safetensors|675509688|bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9"
)

checkpoint_complete() {
  local entry relative expected_size expected_sha path
  for entry in "${files[@]}"; do
    IFS='|' read -r relative expected_size expected_sha <<<"$entry"
    path="${target_dir}/${relative}"
    [[ -f "$path" ]] || return 1
    [[ "$(stat -c %s "$path")" == "$expected_size" ]] || return 1
  done
  [[ -f "${target_dir}/LICENSE.qwen-research" ]] || return 1
}

mkdir -p "$target_dir"

if [[ -f "$manifest" ]] \
  && jq -e --arg repository "$repository" --arg revision "$revision" \
    '.repository == $repository and .revision == $revision' "$manifest" >/dev/null \
  && checkpoint_complete; then
  echo "Qwen-Image 2.1 checkpoint already materialized and verified: $target_dir"
  exit 0
fi

download_verified() {
  local relative="$1"
  local expected_size="$2"
  local expected_sha="$3"
  local output="${target_dir}/${relative}"
  local partial="${output}.part"
  local url="https://huggingface.co/${repository}/resolve/${revision}/${relative}?download=true"

  mkdir -p "$(dirname "$output")"

  if [[ -f "$output" && "$(stat -c %s "$output")" == "$expected_size" ]] \
    && echo "${expected_sha}  ${output}" | sha256sum --check --status; then
    echo "Verified existing ${relative}"
    return
  fi

  curl --fail --location --retry 8 --retry-all-errors --retry-delay 2 \
    --continue-at - --output "$partial" "$url"

  if [[ "$(stat -c %s "$partial")" != "$expected_size" ]]; then
    echo "size mismatch for ${relative}" >&2
    exit 1
  fi
  echo "${expected_sha}  ${partial}" | sha256sum --check --status
  mv "$partial" "$output"
}

for entry in "${files[@]}"; do
  IFS='|' read -r relative expected_size expected_sha <<<"$entry"
  download_verified "$relative" "$expected_size" "$expected_sha"
done

license_output="${target_dir}/LICENSE.qwen-research"
license_partial="${license_output}.part"
curl --fail --location --retry 5 --retry-all-errors \
  --output "$license_partial" \
  "https://huggingface.co/${license_repository}/resolve/${license_revision}/LICENSE"
echo "8dc973f024ff95966bea25866efa443fd16776dcb1001e681e3d467ea572b28d  ${license_partial}" \
  | sha256sum --check --status
mv "$license_partial" "$license_output"

manifest_tmp="${manifest}.part"
jq -n \
  --arg repository "$repository" \
  --arg revision "$revision" \
  --arg licenseRepository "$license_repository" \
  --arg licenseRevision "$license_revision" \
  '{repository: $repository, revision: $revision, licenseRepository: $licenseRepository,
    licenseRevision: $licenseRevision,
    precision: "INT8 ConvRot diffusion and text encoder; BF16 VAE"}' >"$manifest_tmp"
mv "$manifest_tmp" "$manifest"

echo "Qwen-Image 2.1 checkpoint materialized and verified: $target_dir"
