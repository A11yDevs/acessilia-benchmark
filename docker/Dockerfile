FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive UV_PYTHON_INSTALL_DIR=/opt/python UV_CACHE_DIR=/benchmark/data/.cache/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git curl python3 python3-venv libglib2.0-0 libgl1 \
    texlive-latex-extra texlive-fonts-recommended ghostscript fontconfig nodejs \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/uv && /opt/uv/bin/pip install --no-cache-dir uv==0.13.0
ENV PATH="/opt/uv/bin:$PATH" ACESSILIA_BENCHMARK_WORKSPACE=/benchmark
WORKDIR /benchmark
COPY pyproject.toml README.md ./
COPY src ./src
COPY datasets/registry.json ./datasets/registry.json
COPY evaluation/pyproject.toml evaluation/render-tools.lock.json ./evaluation/
COPY docker/entrypoint.sh /usr/local/bin/benchmark-entrypoint
RUN uv sync --extra datasets --no-dev --python 3.11.17 \
    && git config --global --add safe.directory /opt/core-src
ENTRYPOINT ["/usr/local/bin/benchmark-entrypoint"]
