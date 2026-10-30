#!/bin/sh
# Yersinia compilado en vendor/. Ataca capa 2 (DHCP, STP, VTP, CDP): pide root.
here=$(cd "$(dirname "$0")/.." && pwd)
exec sudo "$here/vendor/yersinia/src/yersinia" "$@"
