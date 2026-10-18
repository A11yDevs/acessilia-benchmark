#!/usr/bin/env bash
set -euo pipefail
for argument in "$@"; do
    if [[ "$argument" == "--help" || "$argument" == "-h" ]]; then
        exec /benchmark/.venv/bin/acessilia-benchmark run "$@"
    fi
done
if [[ ! -f /core/pyproject.toml || ! -e /core/.git ]]; then
    echo 'Monte um checkout Git do Acessilia em /core (ACESSILIA_REPO).' >&2
    exit 1
fi
# Build local Core/SDK packages in a disposable copy; build backends may write
# egg-info into their sources. Never write to the mounted checkout or copy venvs.
mkdir -p /opt/core-src
tar -C /core --exclude='.venv' --exclude='venv' --exclude='__pycache__' \
    --exclude='./data' --exclude='./logs' --exclude='./temp' --exclude='.cache' \
    --exclude='.pytest_cache' --exclude='./build' --exclude='./dist' \
    --exclude='*.egg-info' -cf - . | tar -C /opt/core-src --no-same-owner -xf -
core_sync=(uv sync --project /opt/core-src --no-dev --no-editable --python 3.11.17)
if [[ -f /core/uv.lock ]]; then
    core_sync+=(--frozen)
else
    echo 'Core sem uv.lock: gere o lock antes de usar Docker para fixar dependências.' >&2
    exit 1
fi
UV_PROJECT_ENVIRONMENT=/opt/core-venv "${core_sync[@]}"
exec /benchmark/.venv/bin/acessilia-benchmark run "$@" \
    --acessilia-repo /opt/core-src --python /opt/core-venv/bin/python
