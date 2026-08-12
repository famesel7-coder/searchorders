#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="/opt/searchorders"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo ${0}"
  exit 1
fi

if [[ ! -f "${project_dir}/compose.yaml" ]]; then
  echo "Repository must be located at ${project_dir}"
  exit 1
fi

install -m 0644 "${project_dir}/deploy/search-orders.service" /etc/systemd/system/search-orders.service
install -m 0644 "${project_dir}/deploy/search-orders.timer" /etc/systemd/system/search-orders.timer

systemctl daemon-reload
systemctl enable --now search-orders.timer
systemctl list-timers search-orders.timer --no-pager

