#!/usr/bin/env bash
set -euo pipefail

# A bind-mounted episode workspace already contains the generated originals and
# later invocations contain the agent's edits.  Only seed an empty workspace;
# copying on every action would erase a multi-turn repair.
if [ -z "$(find /workspace -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
  cp -a /originals/. /workspace/
fi
chown -R agent:agent /workspace /tmp
if [ -d /submission ]; then
  chown -R agent:agent /submission || true
fi
cd /workspace
if [ "$#" -gt 0 ]; then
  exec su -s /bin/bash agent -- "$@"
fi
exec su -s /bin/bash agent
