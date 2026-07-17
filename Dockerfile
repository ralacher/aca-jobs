FROM cgr.dev/chainguard/python:latest-dev@sha256:bee63d1fd86c4b31dd2df85bb383be142e8067486e3d469265edb850af93e8e4 AS builder

USER 0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
RUN python -m venv /venv \
    && /venv/bin/pip install .

FROM cgr.dev/chainguard/python:latest@sha256:ce9aaca1f826f7f963cd031e98f8c19f993b1843096d395ea919b646e72cb8de

ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /venv /venv
COPY --chown=nonroot:nonroot jobs/ ./jobs/

USER 65532:65532

ENTRYPOINT ["/venv/bin/batchjobs-run"]
CMD ["--help"]
