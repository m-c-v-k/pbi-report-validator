# syntax=docker/dockerfile:1

# Build stage: install the package and its runtime dependencies into a venv.
# EXTRAS names an optional extra to include (`ai` for the -ai image variant).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58 AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
ARG EXTRAS=""
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project ${EXTRAS:+--extra "$EXTRAS"}
COPY src ./src
RUN uv sync --locked --no-dev --no-editable ${EXTRAS:+--extra "$EXTRAS"}

# Runtime stage: only Python and the venv, run as a non-root user.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
LABEL org.opencontainers.image.source="https://github.com/m-c-v-k/pbi-report-validator" \
      org.opencontainers.image.description="Compare two versions of a Power BI report (PBIP) and report what changed." \
      org.opencontainers.image.licenses="MIT"
# git for `pbi-validate changed`, which reads the repository mounted at /work.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
USER app
WORKDIR /work
ENTRYPOINT ["pbi-validate"]
CMD ["--help"]
