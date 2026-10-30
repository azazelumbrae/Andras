#!/bin/sh
# Ejecuta una herramienta del arsenal dentro del contenedor andras/arsenal.
# Uso: scripts/in-docker.sh <comando> [args...]
# Con terminal se abre interactivo; desde un script (sin tty) sólo con -i.
set -e
here=$(cd "$(dirname "$0")/.." && pwd)
if ! docker image inspect andras/arsenal >/dev/null 2>&1; then
  echo "construyendo andras/arsenal (una vez)…" >&2
  docker build -q -f "$here/docker/arsenal.Dockerfile" -t andras/arsenal "$here" >&2
fi
flags="-i"
if [ -t 0 ] && [ -t 1 ]; then
  flags="-it"
fi
exec docker run --rm $flags --network host --privileged \
  -v "$PWD:/work" -w /work andras/arsenal "$*"
