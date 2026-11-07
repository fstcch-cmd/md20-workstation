#!/bin/bash
# MD20 OWNER TOOL (macOS/Linux): sign a licence for THIS computer with your private key and install it.
# Do not give this file to students.  The private key is only read.  Usage: bash MD20-Unlock-This-PC.command PRIVATE.pem
here="$(cd "$(dirname "$0")" && pwd)"
md20=""
for c in "${MD20_ROOT:-/nonexistent}/md20" "$here/../../../md20" "$HOME/MD20/md20"; do
  if [ -x "$c" ]; then md20="$c"; break; fi
done
[ -n "$md20" ] || { echo "MD20 is not installed on this computer. Run Install-MD20.command first."; exit 1; }
export PYTHONUTF8=1
key="$1"
if [ -z "$key" ]; then
  if [ "$(uname -s)" = "Darwin" ] && command -v osascript >/dev/null 2>&1; then
    key="$(osascript -e 'POSIX path of (choose file with prompt "Choose your PRIVATE key (md20_owner_private.pem)")' 2>/dev/null)"
  else read -r -p "Path of your PRIVATE key (.pem): " key; fi
fi
[ -n "$key" ] || { echo "No key chosen. Nothing was done."; exit 0; }
code="$("$md20" license machine | tail -n 1)"
echo "Machine code of this computer: $code"
who="Owner_$(hostname | tr -c 'A-Za-z0-9_-' '_')"
out="$HOME/Desktop/MD20_licenses/own_pc_$(date +%Y%m%d_%H%M%S).md20license"; mkdir -p "$(dirname "$out")"
"$md20" license issue --key "$key" --name "$who" --days 3650 --machine "$code" --out "$out" || exit 1
"$md20" license install "$out"
