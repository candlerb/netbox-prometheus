#!/bin/sh
set -e

# Sleep interval for how often to poll (300s) This can be controlled by setting SLEEP_INT env var.
sleep_duration="${SLEEP_INT:-300}"

while true; do (python3 netbox_prometheus.py; sleep $sleep_duration); done

