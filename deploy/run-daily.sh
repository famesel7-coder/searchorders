#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="${SEARCH_ORDERS_DIR:-/opt/searchorders}"
output_dir="${project_dir}/output"
stamp="$(TZ=Europe/Moscow date +%Y-%m-%dT%H-%M)"
output_name="leads-${stamp}.json"

mkdir -p "${output_dir}"
cd "${project_dir}"

docker compose run --rm search-orders \
  hh \
  --hours 30 \
  --max-results 150 \
  --area 113 \
  --output "/app/output/${output_name}"

ln -sfn "${output_name}" "${output_dir}/latest.json"

