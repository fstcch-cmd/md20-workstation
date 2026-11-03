[繁中](MAC.md) · [English](MAC.en.md) · [日本語](MAC.ja.md) · [한국어](MAC.ko.md)

# MD20 學生操作說明：macOS

你需要 macOS 12 以上（Apple Silicon M1–M4 或 Intel 都可以）、至少 8 GB 的可用磁碟空間，以及網路。Mac 沒有 CUDA，程式會用 OpenCL 或 CPU 計算，速度比 NVIDIA 筆電慢。**課堂案例請用 classroom 等級。**

## 1. 安裝（只做一次，約 15–30 分鐘）
1. 下載 `MD20-macOS-v0.1.0a11.zip`，在「下載項目」裡雙擊解壓縮，會得到資料夾 `MD20-v0.1.0a11`。
2. 打開「終端機」（在 Launchpad 搜尋 Terminal），貼上下面這行，按 Enter。

```
bash ~/Downloads/MD20-v0.1.0a11/Install-MD20.command
```
   - 最後出現「完成 Done.」才算裝好。如果出現錯誤，把終端機裡的文字複製給老師。
   - 程式會裝在家目錄的 `MD20` 資料夾。下載的那個資料夾之後可以刪掉。
3. 裝好後，桌面會多一個 `MD20-GUI.command`。

## 2. 每次使用
- 圖形介面：雙擊桌面的 `MD20-GUI.command`，再用瀏覽器打開 http://127.0.0.1:8020 。計算進行時，**不要關掉那個終端機視窗**。瀏覽器可以關，用完再把終端機視窗關掉。
- 第一次如果出現「無法打開」，在檔案上按右鍵，選「打開」，再按一次「打開」。
- 介面語言：右上角的語言選單可以切換 English、繁體中文、日本語、한국어。
- 想一邊計算一邊寫報告：右上角的資源選單平常顯示「平衡（預設）」，改選「省資源：可同時寫報告」。從下一個計算步驟開始生效。電腦沒有要用的時候，可以選「全速：電腦閒置時」。
- 命令列：在終端機輸入下面這行。

```
~/MD20/md20 doctor
```
找「選用 OpenMM 平台」這一行。寫 OpenCL 表示有用到顯示晶片。寫 CPU 也能跑，只是比較慢。

```
~/MD20/md20 demo
```
這是不做真正計算的示範流程，1 分鐘內會跑完並產生報告。跑得完就表示安裝正常。

## 3. 第一個真實案例（胰蛋白酶與苯甲脒）
```
cd ~/Desktop
~/MD20/md20 pipeline example > trypsin.json
sed -i '' 's/"tier": "teaching"/"tier": "classroom"/' trypsin.json
~/MD20/md20 pipeline run trypsin.json --project first_case
```
- 第三行把等級改成 classroom（2 ns）。在 Mac 上估計要 2–4 小時，還沒有實測過。
- 專案名稱只用英文字母和數字。
- 筆電要**接上電源**，也不要讓它進入睡眠。
- 中途關掉終端機沒關係，**再打一次最後一行，會從中斷的地方繼續**。
- 結果在「文件」資料夾裡的 `MD20_Projects/first_case`，打開裡面的 `report.html`。

## 4. 出問題時
執行下面這行，把輸出複製給老師。
```
~/MD20/md20 doctor --no-benchmark
```
