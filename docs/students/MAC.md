# MD20 學生操作說明：macOS

需要：macOS 12 以上（Apple Silicon M1–M4 或 Intel）、可用磁碟 ≥ 8 GB、網路。Mac 沒有 CUDA，會用 OpenCL 或 CPU，比 NVIDIA 筆電慢，
**課堂案例請用 classroom 等級**。

## 1. 安裝（一次，約 15–30 分鐘）
1. 下載 **`MD20-macOS-v0.1.0a3.zip`**，在「下載項目」裡**雙擊解壓**，會得到資料夾 `MD20-v0.1.0a3`。
2. 打開「終端機」（Launchpad 搜尋 Terminal），貼上下面一行，按 Enter：

```
bash ~/Downloads/MD20-v0.1.0a3/Install-MD20.command
```
   - 最後出現「完成 Done.」才算裝好；出現錯誤就把終端機的文字複製給老師。
   - 程式裝在家目錄的 `MD20` 資料夾；下載的資料夾之後可以刪除。
3. 桌面會多一個 **`MD20-GUI.command`**。

## 2. 每次使用
- 圖形介面：**雙擊桌面的 `MD20-GUI.command`**，再用瀏覽器打開 http://127.0.0.1:8020 。用完關掉那個終端機視窗即可。
  （第一次若出現「無法打開」，在檔案上按右鍵 →「打開」→「打開」。）
- 命令列（在終端機輸入）：

```
~/MD20/md20 doctor
```
看「選用平台」：OpenCL 表示用到顯示晶片；CPU 也能跑，較慢。

```
~/MD20/md20 demo
```
1 分鐘內跑完示範流程並產生報告，確認安裝正常。

## 3. 第一個真實案例（胰蛋白酶＋苯甲脒）
```
cd ~/Desktop
~/MD20/md20 pipeline example > trypsin.json
sed -i '' 's/"tier": "teaching"/"tier": "classroom"/' trypsin.json
~/MD20/md20 pipeline run trypsin.json --project first_case
```
- 第三行把等級改成 classroom（2 ns），Mac 上約 2–4 小時。筆電請**接電源**、不要讓它睡眠。
- 中途關掉終端機沒關係，**重打最後一行會從中斷處繼續**。
- 結果在「文件／MD20_Projects／first_case」；打開裡面的 `report.html`。

## 4. 出問題時
```
~/MD20/md20 doctor --no-benchmark
```
把輸出複製給老師。
