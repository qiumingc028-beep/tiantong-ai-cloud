#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "usage: $0 <backend|worker> <image-name> <docker-archive>" >&2
    exit 64
}

[[ $# -eq 3 ]] || usage

service=$1
image_name=$2
output_archive=$3
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

case "$service" in
    backend) dockerfile="$root/Dockerfile.backend" ;;
    worker) dockerfile="$root/Dockerfile.worker" ;;
    *) usage ;;
esac

git_sha=${GIT_SHA:-$(git -C "$root" rev-parse HEAD)}
source_date_epoch=$(git -C "$root" show -s --format=%ct "$git_sha")

[[ "$git_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$source_date_epoch" =~ ^[0-9]+$ ]]
[[ ! -e "$output_archive" ]]

export SOURCE_DATE_EPOCH=$source_date_epoch

python_base=python:s12-pinned-8a7e7cc04fd3-amd64
expected_python_id=sha256:db8e83a44af476c636a6a753adace39ad37863b63c0afd2862db7bbafeeb3944
expected_python_manifest=sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b
actual_python_id=$(docker image inspect "$python_base" --format '{{.Id}}')
[[ "$actual_python_id" == "$expected_python_id" ]]
printf 'PYTHON_BASE_IMAGE_ID=%s\n' "$actual_python_id"
printf 'PYTHON_BASE_SOURCE_MANIFEST=%s\n' "$expected_python_manifest"

docker buildx build \
    --builder default \
    --platform linux/amd64 \
    --network=none \
    --no-cache \
    --pull=false \
    --provenance=false \
    --sbom=false \
    --build-arg "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH" \
    --label "org.opencontainers.image.revision=$git_sha" \
    --output "type=docker,name=$image_name,dest=$output_archive,rewrite-timestamp=true" \
    --file "$dockerfile" \
    "$root"

printf 'SERVICE=%s\n' "$service"
printf 'GIT_SHA=%s\n' "$git_sha"
printf 'SOURCE_DATE_EPOCH=%s\n' "$SOURCE_DATE_EPOCH"
printf 'IMAGE_NAME=%s\n' "$image_name"
printf 'OUTPUT_ARCHIVE=%s\n' "$output_archive"
sha256sum "$output_archive"
