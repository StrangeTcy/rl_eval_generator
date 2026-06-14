#!/usr/bin/env bash
set -euo pipefail

cp -a /originals/. /workspace/
chown -R agent:agent /workspace /tmp
if [ -d /submission ]; then
  chown -R agent:agent /submission || true
fi
cd /workspace
exec su -s /bin/bash agent
