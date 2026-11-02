# MD20 學生操作說明：Windows

需要：Windows 10／11、可用磁碟 ≥ 8 GB、網路。有 NVIDIA 顯示卡會自動用 GPU（CUDA）；沒有也能跑（OpenCL／CPU，較慢）。

## 1. 安裝（一次，約 15–30 分鐘）
1. 到老師給的下載頁下載 **`MD20-Windows-v0.1.0a3.zip`**。
2. 在檔案上按右鍵 →「解壓縮全部」。
3. 進入解壓出的資料夾，**雙擊 `Install-MD20.cmd`**。
   - 跳出藍色「Windows 已保護您的電腦」：按「其他資訊」→「仍要執行」。
   - 視窗最後出現「完成」才算裝好；出現錯誤就把整個視窗的文字拍照傳給老師。
4. 桌面會多一個 **`MD20-GUI.cmd`**。

## 2. 每次使用
- 圖形介面：**雙擊桌面的 `MD20-GUI.cmd`**，瀏覽器會打開 http://127.0.0.1:8020 。用完關掉那個黑色視窗即可。
- 命令列：按 `Win + R`，輸入 `cmd`，按 Enter，然後輸入：

```
%LOCALAPPDATA%\MD20\md20.cmd doctor
```
看「選用平台」：CUDA 或 OpenCL 表示用到顯示卡；CPU 表示沒用到（仍可跑，較慢）。

```
%LOCALAPPDATA%\MD20\md20.cmd demo
```
1 分鐘內跑完一個不需要計算的示範流程並產生報告，確認安裝正常。

## 3. 第一個真實案例（胰蛋白酶＋苯甲脒，約 1–1.5 小時）
```
cd %USERPROFILE%\Desktop
%LOCALAPPDATA%\MD20\md20.cmd pipeline example > trypsin.json
%LOCALAPPDATA%\MD20\md20.cmd pipeline run trypsin.json --project first_case
```
- 筆電請**接電源**（用電池時會自動暫停）。
- 中途關掉視窗沒關係，**重打最後一行會從中斷處繼續**。
- 結果在「文件\MD20_Projects\first_case」；打開裡面的 `report.html`。

## 4. 出問題時
把這一行的輸出拍照或複製給老師：
```
%LOCALAPPDATA%\MD20\md20.cmd doctor --no-benchmark
```
