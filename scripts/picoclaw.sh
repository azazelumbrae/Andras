#!/bin/sh
# PicoClaw vendorizado: agente personal en Go, con workspace propio dentro del repo.
here=$(cd "$(dirname "$0")/.." && pwd)
export PICOCLAW_HOME="${PICOCLAW_HOME:-$here/data/picoclaw}"
mkdir -p "$PICOCLAW_HOME"
exec "$here/vendor/picoclaw/picoclaw" "$@"
