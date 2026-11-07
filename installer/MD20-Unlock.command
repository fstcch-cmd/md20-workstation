#!/bin/bash
# MD20 unlock (student, macOS/Linux): import the licence file (.md20license) your instructor sent you.
# Usage: double-click, or  bash MD20-Unlock.command [path/to/file.md20license]
here="$(cd "$(dirname "$0")" && pwd)"
md20=""
for c in "${MD20_ROOT:-/nonexistent}/md20" "$here/md20" "$here/../../md20" "$HOME/MD20/md20"; do
  if [ -x "$c" ]; then md20="$c"; break; fi
done
if [ -z "$md20" ]; then
  echo "MD20 is not installed on this computer. Run Install-MD20.command first, then run this again."
  [ -t 0 ] && read -r -p "Press Enter to close " _
  exit 1
fi
export PYTHONUTF8=1
echo "=== MD20 unlock ==="
code="$("$md20" license machine 2>/dev/null | tail -n 1)"
echo "Machine code of this computer: $code"
if command -v pbcopy >/dev/null 2>&1; then printf '%s' "$code" | pbcopy && echo "(copied to the clipboard; send it to your instructor when you ask for a licence)"; fi
echo
file="$1"
if [ -z "$file" ]; then
  if [ "$(uname -s)" = "Darwin" ] && command -v osascript >/dev/null 2>&1; then
    file="$(osascript -e 'POSIX path of (choose file with prompt "Choose the MD20 licence file (.md20license)")' 2>/dev/null)"
  else
    read -r -p "Path of the licence file (.md20license): " file
  fi
fi
if [ -z "$file" ]; then echo "No file chosen. Nothing was changed."; exit 0; fi
echo "Licence file: $file"
"$md20" license install "$file"
rc=$?
echo
if [ "$rc" -eq 0 ]; then echo "Done. MD20 is unlocked on this computer."; else echo "The licence was NOT installed. Read the message above, or send a photo of this window to your instructor."; fi
[ -t 0 ] && read -r -p "Press Enter to close " _
exit "$rc"
