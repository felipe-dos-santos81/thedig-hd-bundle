#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# bompDecodeLine as a standalone TU: verbatim upstream body, wrapped in the
# namespace its own header declares it in (scumm/bomp.h: namespace Scumm).
{
  printf '#include "shim.h"\n'
  printf '#include "scumm/bomp.h"\n'
  printf 'namespace Scumm {\n'
  awk '/^void bompDecodeLine\(byte \*dst, const byte \*src, int len, bool setZero\)/,/^}/' upstream/engines/scumm/bomp.cpp
  printf '} // namespace Scumm\n'
} > bomp_core.cpp
grep -q 'setZero' bomp_core.cpp || { echo "bomp extraction failed" >&2; exit 1; }
# NutRenderer::codec21 body (verbatim statements) wrapped in a free function.
# The body is lines 66-93 of nut_renderer.cpp; only the signature differs.
{
  printf '#include "shim.h"\n'
  printf 'void nut_codec21(byte *dst, const byte *src, int width, int height, int pitch) {\n'
  sed -n '/^void NutRenderer::codec21(/,/^}/p' upstream/engines/scumm/nut_renderer.cpp | sed '1d;$d'
  printf '}\n'
} > nut_core.cpp
grep -q 'dstPtrNext' nut_core.cpp || { echo "codec21 extraction failed" >&2; exit 1; }
# bomp_core.cpp + nut_core.cpp + codec1.cpp + codec37.cpp verbatim + oracle_main.cpp
clang++ -O1 -w -std=c++17 -I upstream/engines -I inc -lz \
  -o san-oracle bomp_core.cpp nut_core.cpp \
  upstream/engines/scumm/smush/codec1.cpp \
  upstream/engines/scumm/smush/codec37.cpp oracle_main.cpp
echo built: vendor/san-oracle/san-oracle
