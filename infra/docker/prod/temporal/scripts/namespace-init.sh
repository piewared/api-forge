#!/bin/sh
set -e

echo "[init] waiting for cluster health..."
for i in $(seq 1 60); do
  temporal --command-timeout 2s operator cluster health && break || sleep 2
done

echo "[init] describing namespace..."
if temporal operator namespace describe -n default >/dev/null 2>&1; then
  echo "[init] namespace already exists"
else
  echo "[init] creating namespace..."
  temporal operator namespace create -n default --retention 7d
  echo "[init] created"
fi
