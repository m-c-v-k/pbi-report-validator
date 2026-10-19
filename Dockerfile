# syntax=docker/dockerfile:1

# Build stage: install the package and its runtime dependencies into a venv.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58 AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# Runtime stage: only Python and the venv, run as a non-root user.
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
LABEL org.opencontainers.image.source="https://github.com/m-c-v-k/pbi-report-validator" \
      org.opencontainers.image.description="Compare two versions of a Power BI report (PBIP) and report what changed." \
      org.opencontainers.image.licenses="MIT"
RUN useradd --create-home --uid 1000 app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
USER app
WORKDIR /work
ENTRYPOINT ["pbi-validate"]
CMD ["--help"]
