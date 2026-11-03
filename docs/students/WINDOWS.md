[繁中](WINDOWS.md) · [English](WINDOWS.en.md) · [日本語](WINDOWS.ja.md) · [한국어](WINDOWS.ko.md)

# MD20 學生操作說明：Windows

你需要 Windows 10 或 11、至少 8 GB 的可用磁碟空間，以及網路。有 NVIDIA 顯示卡時，程式會自動用 GPU（CUDA）計算。沒有 NVIDIA 顯示卡也能跑，會改用 OpenCL 或 CPU，只是比較慢。

## 1. 安裝（只做一次，約 15–30 分鐘）
1. 到老師給的下載頁，下載 `MD20-Windows-v0.1.0a12.zip`。
2. 在檔案上按右鍵，選「解壓縮全部」。
3. 打開解壓出來的資料夾，雙擊 `Install-MD20.cmd`。
   - 如果跳出藍色的「Windows 已保護您的電腦」，先按「其他資訊」，再按「仍要執行」。
   - 視窗最後出現「完成」才算裝好。如果出現錯誤，把整個視窗的文字拍照傳給老師。
4. 裝好後，桌面會多一個 `MD20-GUI.cmd`。

## 2. 每次使用
- 圖形介面：雙擊桌面的 `MD20-GUI.cmd`，瀏覽器會打開 http://127.0.0.1:8020 。計算進行時，**不要關掉那個黑色視窗**。瀏覽器可以關，用完再把黑色視窗關掉。
- 介面語言：右上角的語言選單可以切換 English、繁體中文、日本語、한국어。
- 想一邊計算一邊寫報告：右上角的資源選單平常顯示「平衡（預設）」，改選「省資源：可同時寫報告」。從下一個計算步驟開始生效。電腦沒有要用的時候，可以選「全速：電腦閒置時」。
- 命令列：按 `Win + R`，輸入 `cmd`，按 Enter，再輸入下面這行。

```
%LOCALAPPDATA%\MD20\md20.cmd doctor
```
找「選用 OpenMM 平台」這一行。寫 CUDA 或 OpenCL 表示有用到顯示卡。寫 CPU 表示沒用到，一樣可以跑，只是比較慢。

```
%LOCALAPPDATA%\MD20\md20.cmd demo
```
這是不做真正計算的示範流程，1 分鐘內會跑完並產生報告。跑得完就表示安裝正常。

## 3. 第一個真實案例（胰蛋白酶與苯甲脒）
```
cd %USERPROFILE%\Desktop
%LOCALAPPDATA%\MD20\md20.cmd pipeline example > trypsin.json
notepad trypsin.json
%LOCALAPPDATA%\MD20\md20.cmd pipeline run trypsin.json --project first_case
```
- 第三行會打開記事本。把 `"tier": "teaching"` 改成 `"tier": "classroom"`（2 ns），存檔後關掉記事本。
- 在 RTX 4060 筆電上，classroom 實測 76.5 分鐘。不改的話是 teaching（10 ns），估計約 3 小時。沒有 NVIDIA 顯示卡會慢很多，請用 classroom。
- 專案名稱只用英文字母和數字。用中文命名，資料夾名稱會變成看不懂的代碼。
- 筆電要**接上電源**。用電池時計算會自動暫停。
- 中途關掉視窗沒關係，**再打一次最後一行，會從中斷的地方繼續**。
- 結果在「文件」資料夾裡的 `MD20_Projects\first_case`，打開裡面的 `report.html`。

## 4. 胜肽當配體（直接貼序列）
1. **先裝摺疊工具（只做一次，上課前在家裝）**：雙擊解壓資料夾裡的 `Install-Folding.cmd`。它會下載 PyTorch 和模型權重，共數 GB，約 20–60 分鐘，最後會試摺一個胜肽。最後看到 Done 就裝好了。也可以在介面的「電腦狀態」頁按「一鍵安裝」。
2. 在快速模式的配體欄，直接貼上序列，名稱寫在前面：
   ```
   MEL GIGAVLKVLTTGLPALISWIKRKRQQ
   ```
   只貼序列也可以，名稱會自動取為 PEP。不用再加 `peptide:`。
3. 10 個殘基以上的胜肽，旁邊的「先摺疊這個胜肽」會自動勾起：程式先預測結構，再對接、跑 MD。不想摺疊就取消勾選。少於 10 個殘基的胜肽單獨存在時通常沒有固定結構，不摺疊，直接由對接改變構形。
4. 預測信心太低（pLDDT 低於 50）或沒有裝摺疊工具時，流程會停在「摺疊」，並列出可以怎麼做：安裝工具、上傳 AlphaFold Server 的結構，或不摺疊。
5. 序列只由 C、N、P、S、F、I 這幾個字母組成時（例如 `CCCCCN`），它也可能是 SMILES，程式會請你在前面加 `peptide:` 或 `smiles:`。

## 5. 出問題時
執行下面這行，把輸出拍照或複製給老師。
```
%LOCALAPPDATA%\MD20\md20.cmd doctor --no-benchmark
```
