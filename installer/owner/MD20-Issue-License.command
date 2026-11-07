#!/bin/bash
# MD20 OWNER TOOL (macOS/Linux): sign licence files with your private key.  Do not give this file to students.
# The private key is only read.  Usage: bash MD20-Issue-License.command PRIVATE.pem
#   one person:   bash MD20-Issue-License.command PRIVATE.pem "Name" [days|YYYY-MM-DD] [machine-code]
#   many people:  bash MD20-Issue-License.command PRIVATE.pem list.csv     (name, days or date, machine code)
here="$(cd "$(dirname "$0")" && pwd)"
md20=""
for c in "${MD20_ROOT:-/nonexistent}/md20" "$here/../../../md20" "$HOME/MD20/md20"; do
  if [ -x "$c" ]; then md20="$c"; break; fi
done
[ -n "$md20" ] || { echo "MD20 is not installed on this computer. Run Install-MD20.command first."; exit 1; }
export PYTHONUTF8=1
key="$1"; second="$2"
[ -n "$key" ] && [ -n "$second" ] || { sed -n 2,6p "$0"; exit 2; }
out="$HOME/Desktop/MD20_licenses/$(date +%Y%m%d_%H%M%S)"; mkdir -p "$out"
if [ -f "$second" ]; then
  "$md20" license issue-batch --key "$key" --csv "$second" --out "$out"
else
  csv="$out/_input.csv"
  python3 - "$csv" "$second" "${3:-}" "${4:-}" <<'PY'
import csv, sys
with open(sys.argv[1], "w", newline="", encoding="utf-8-sig") as fh:
    csv.writer(fh).writerow(sys.argv[2:5])
PY
  "$md20" license issue-batch --key "$key" --csv "$csv" --out "$out"
fi
rc=$?
[ "$rc" -eq 0 ] && echo "Licence files are in: $out (issued.csv lists them)"
exit "$rc"
