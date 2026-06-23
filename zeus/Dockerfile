FROM python:3.12-slim

# CBC (the LP solver behind PuLP) ships as a manylinux wheel, so no system
# solver packages are needed.
WORKDIR /app

COPY pyproject.toml README.md ./
COPY zeus ./zeus

RUN pip install --no-cache-dir .

# config.yaml is mounted at runtime (keeps secrets out of the image).
VOLUME ["/config", "/app/reports"]

ENTRYPOINT ["zeus", "--config", "/config/config.yaml"]
