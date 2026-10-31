FROM python:3.15-slim AS build
WORKDIR /src
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY baton ./baton
RUN python -m venv /opt/venv && /opt/venv/bin/pip install .

FROM python:3.15-slim
LABEL org.opencontainers.image.source="https://github.com/frederikb96/baton" \
      org.opencontainers.image.description="Self-hosted remote for Spotify: watch API, web page and Spotify login" \
      org.opencontainers.image.licenses="MIT"
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BATON_DATA_DIR=/data
COPY --from=build /opt/venv /opt/venv
RUN mkdir /data && chown 1000:1000 /data
USER 1000:1000
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"]
CMD ["python", "-m", "baton"]
