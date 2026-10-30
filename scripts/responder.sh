#!/bin/sh
# Responder vendorizado. Envenena LLMNR/NBT-NS/mDNS: necesita root y estar en la red local.
here=$(cd "$(dirname "$0")/.." && pwd)
exec sudo "$here/.venv/bin/python" "$here/vendor/responder/Responder.py" "$@"
