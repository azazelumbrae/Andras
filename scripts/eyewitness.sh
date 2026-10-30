#!/bin/sh
# EyeWitness vendorizado: capturas y huellas de portales. Usa Chrome ya instalado.
here=$(cd "$(dirname "$0")/.." && pwd)
exec "$here/.venv/bin/python" "$here/vendor/eyewitness/Python/EyeWitness.py" "$@"
