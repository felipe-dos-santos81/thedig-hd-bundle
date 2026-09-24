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
# codec37.cpp verbatim + oracle_main.cpp
clang++ -O1 -w -std=c++17 -I upstream/engines -I inc -lz \
  -o san-oracle bomp_core.cpp upstream/engines/scumm/smush/codec37.cpp oracle_main.cpp
echo built: vendor/san-oracle/san-oracle
