#!/bin/bash
# MD20 peptide folding (OmegaFold) for macOS — double-click AFTER Install-MD20.command has finished (D-85).
# Downloads PyTorch and the model weights (several GB, 20-60 minutes), then folds one test peptide.
ROOT="${MD20_ROOT:-$HOME/MD20}"
if [ ! -x "$ROOT/md20" ]; then
  echo "MD20 尚未安裝在 $ROOT。請先執行 Install-MD20.command。 / MD20 is not installed in $ROOT. Run Install-MD20.command first."
  rc=2
else
  "$ROOT/md20" setup-fold --engine omegafold --yes --warmup
  rc=$?
fi
echo
if [ "$rc" -ne 0 ]; then
  echo "摺疊工具安裝中止（exit ${rc}）。請把上面的訊息傳給老師。 / Folding setup stopped (exit $rc). Send the messages above to your instructor."
else
  echo "完成。在配體欄輸入胜肽序列就會自動摺疊。 / Done. Peptide sequences typed in the ligand box are now folded automatically."
fi
if [ -t 0 ]; then read -r -p "按 Enter 關閉 / Press Enter to close " _; fi
exit "$rc"
