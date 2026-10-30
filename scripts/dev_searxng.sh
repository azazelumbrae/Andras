#!/bin/sh
# SearXNG local para que el agente busque sin depender de buscadores que bloquean.
set -e
cd "$(dirname "$0")/.."
mkdir -p data/searxng
if [ ! -f data/searxng/settings.yml ]; then
  echo "Falta data/searxng/settings.yml (lo crea `andras init --searxng`)." >&2
  exit 1
fi
docker rm -f andras-searxng >/dev/null 2>&1 || true
docker run -d --rm --name andras-searxng -p 8888:8080 \
  -v "$PWD/data/searxng:/etc/searxng" searxng/searxng
echo "SearXNG en http://127.0.0.1:8888 (pon searxng_url en config.json)"
