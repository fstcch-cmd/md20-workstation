#!/bin/bash
# MD20 installer for macOS — double-click in Finder, or in Terminal:  bash Install-MD20.command
# Options are passed through (e.g. MD20_ROOT=/Volumes/Data/MD20 bash Install-MD20.command).
cd "$(dirname "$0")" || exit 1
bash installer/install.sh "$@"
rc=$?
echo
if [ "$rc" -ne 0 ]; then
  echo "安裝中止（exit ${rc}）。請把上面的訊息傳給老師。 / Installation stopped (exit $rc). Send the messages above to your instructor."
else
  echo "完成。雙擊桌面的 MD20-GUI.command 開啟介面。 / Done. Double-click MD20-GUI.command on the Desktop."
fi
if [ -t 0 ]; then read -r -p "按 Enter 關閉 / Press Enter to close " _; fi
exit "$rc"
