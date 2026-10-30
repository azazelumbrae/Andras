#!/bin/sh
# DNSrebinder vendorizado: saltarse la Same-Origin Policy. Necesita root para el puerto 53.
here=$(cd "$(dirname "$0")/.." && pwd)
exec sudo "$here/.venv/bin/python" "$here/vendor/dnsrebinder/dnsrebinder.py" "$@"
