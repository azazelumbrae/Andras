#!/bin/sh
# Lanzador de URLCrazy, vendorizado: el código vive en vendor/urlcrazy y las gemas se
# instalan ahí una sola vez. Ya no está en rubygems, por eso no es una dependencia normal.
set -e
here=$(cd "$(dirname "$0")/.." && pwd)
dir="$here/vendor/urlcrazy"
gems="$dir/vendor/gems"

if [ ! -d "$gems" ]; then
  echo "instalando dependencias de URLCrazy en $gems (una vez)…" >&2
  (cd "$dir" && GEM_HOME="$gems" GEM_PATH="$gems" bundle install --quiet) >&2
fi

GEM_HOME="$gems" GEM_PATH="$gems" exec ruby "$dir/urlcrazy.rb" "$@"
