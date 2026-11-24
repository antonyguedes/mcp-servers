# SPDX-License-Identifier: MIT
# Production headless image: Blender + blender-mcp Streamable HTTP server
FROM ubuntu:24.04

ARG BLENDER_VERSION=4.5.0
ARG BLENDER_SERIES=4.5

ENV DEBIAN_FRONTEND=noninteractive \
    BLENDER_MCP_TRANSPORT=http \
    BLENDER_MCP_HTTP_HOST=0.0.0.0 \
    BLENDER_MCP_HTTP_PORT=8765 \
    BLENDER_MCP_ALLOW_PYTHON=false \
    BLENDER_MCP_PROFILE=full \
    BLENDER_MCP_ALLOWED_DIRS=/workspace \
    BLENDER_MCP_CACHE_DIR=/cache/assets

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    xz-utils \
    python3 \
    libxrender1 \
    libxi6 \
    libxkbcommon0 \
    libgl1 \
    libegl1 \
    libsm6 \
    libxfixes3 \
    libxxf86vm1 \
    && rm -rf /var/lib/apt/lists/*

# Install Blender headless
RUN curl -fsSL "https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" -o /tmp/blender.tar.xz \
    && mkdir -p /opt/blender \
    && tar -xf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 \
    && ln -s /opt/blender/blender /usr/local/bin/blender \
    && rm -f /tmp/blender.tar.xz

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE LICENSING.md ./
COPY packages ./packages

RUN uv sync --frozen --no-dev

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && mkdir -p /workspace /cache/assets

EXPOSE 8765
VOLUME ["/workspace", "/cache"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
