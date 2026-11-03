# Spec: Vina 執行檔的 CPU 使用（D-68、D-70、D-72）

## Vina 怎麼平行（讀 AutoDock-Vina 原始碼 `vina.cpp::global_search`、`parallel_mc.cpp`、`parallel.h`）
- 只有蒙地卡羅搜尋是平行的：開 `--cpu` 條執行緒，分 `exhaustiveness` 個獨立工作 → 最多 **min(--cpu, exhaustiveness)** 條同時忙。
  多配體同時對接也一樣（每個工作複製整個多配體模型）。
- 格點圖計算（`cache::populate`）與最後精修是單執行緒；所以整次執行的平均執行緒數一定略低於上限。
- 推論：exhaustiveness 8 在 16 執行緒電腦上最多約 50% CPU，是設計，不是錯誤。

## MD20 的設定
| 資源模式 | `--cpu`（D-68） | Windows 優先權（D-70） | Windows QoS（D-72） |
|---|---|---|---|
| 省資源 background | ¼ 的邏輯 CPU | IDLE | **EcoQoS**（留在節能核心） |
| 平衡 balanced | 全部 − 2 | NORMAL | **HighQoS** |
| 全速 full | 全部 | NORMAL | **HighQoS** |

QoS 為何必要：Windows 依「擁有視窗的程序及其子孫」的視窗狀態給 QoS（前景 High／可見 Medium／最小化或被遮住 Low），
Low 在混合架構 CPU 只排到節能核心。MD20 GUI 從主控台視窗啟動、學生看瀏覽器 → vina.exe 被降 Low。
明確以 `SetProcessInformation(ProcessPowerThrottling)` 標記會取代依視窗判定的等級。

## 量測（每次 Vina 執行）
`params["vina_runs"]` 每筆：`cpu_requested`、`exhaustiveness`、`threads_possible`＝min(兩者)、`wall_s`、`cpu_s`、
`effective_threads`＝cpu_s／wall_s、`qos`（high／eco／unchanged／None＝非 Windows）。
DecisionLog `docking.run / cpu_use`：中文 `why`；執行 > 2 分鐘且 effective < ½ 上限時 `held_back=True` 並寫出可能原因。
**只是速度提示，不是閘門**（對接結果不受影響，不會 NEEDS_HUMAN）。

## 待驗證
- 筆電（i7-13620H、Windows 11）：新版對接時 `effective_threads` 應接近 `threads_possible`；若仍約 4，D-72 推測錯誤，需在 DECISIONS 更正。
- 手動驗證：對接中把主控台視窗切到前景／最小化，看 vina.exe CPU% 是否在約 100% 與約 25% 之間切換（舊版）。

## 被否決
- 親和性綁 P-core（需辨識核心型別、機型各異）；要求學生把視窗留在前景（只能當驗證）；依機器執行緒數自動調 exhaustiveness（各人結果不同，課堂不可重現——留給使用者決定）。
