#!/bin/sh
# evil-ssdp vendorizado: honeypot UPnP que pesca hashes NTLM. Necesita root y red local.
here=$(cd "$(dirname "$0")/.." && pwd)
exec sudo "$here/.venv/bin/python" "$here/vendor/evil-ssdp/evil_ssdp.py" "$@"
