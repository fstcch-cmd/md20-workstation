# M0 + M1(部分) 狀態報告（2026-10-31）

開發環境限制：本次開發的雲端工作區無法連 PyPI／conda-forge，**OpenMM、RDKit、PDBFixer、OpenFF 未安裝**。
因此下表嚴格分成三類。

## A. 已真實執行並通過測試（本工作區，Python 3.13，numpy/pandas/matplotlib）

| 模組 | 測試 | 內容 |
|---|---|---|
| `engine` chunk 引擎 | `tests/test_engine_fake.py`（7） | 分段執行與封存、損壞 chunk 續跑、identity 不符拒絕、watchdog 連續失敗升級 NEEDS_HUMAN、watchdog dt 減半後恢復、完整 protocol（minimize→NVT→NPT→production）＋圖表、驗收延長建議 |
| `build` 閘門 | `tests/test_build_gates.py`（5） | 乾淨 PDB 通過；docking 損壞 PDB（缺 element、LIG、重複原子名、氫、水、MSE）正確分類；長／短 loop 判定；serial 溢位與輔因子；閘門狀態優先序 |
| `project` 檔案庫 | `tests/test_project_store.py`（4） | 專案／case／run 建立與階段推斷、Windows 保留檔名、便宜指紋、檔案鎖逾時、JSON 備份回退 |
| `sampling` PMF | `tests/test_sampling.py`（4） | window 規劃間距／overlap；WHAM 由合成 umbrella 資料還原平坦 PMF 與諧振井；gap 偵測 |
| `cli demo` | 手動執行 | 專案→case→run→四階段→5 張圖→決策日誌→HTML 報告 |
| `report` | `tests/test_report.py`（1） | 自含 HTML 報告（圖內嵌 base64、方法段落中英、驗收表、閘門表、決策日誌、protocol）；可重現包 zip（含 SHA manifest） |
| `engine.replicas` / `engine.queue` | `tests/test_queue_replicas.py`（4） | 多 replica（seed+1000i）執行與彙總（mean±SD、疊圖）；暫停策略（PAUSE 檔／電池／時段）；chunk 邊界暫停與續跑；佇列暫停後續跑同一組 run 不重複建立 |
| `env.doctor.recommend_tier` | `tests/test_doctor_tier.py`（1） | 由 ns/day 與系統大小推薦 tier 與 ETA |
| `env.doctor` | 手動執行（無 OpenMM 的降級模式） | 硬體探測、套件報告、Markdown 輸出 |

## B. 已寫、未在此執行（需要 OpenMM／RDKit／OpenFF；請在你的機器執行 `pytest tests/test_openmm_integration.py -v`）

| 模組 | 風險點 |
|---|---|
| `engine.backend.OpenMMBackend` | HMR 質量重分配、barostat 參數重設、reporter 關閉；DCD/log 路徑在 Windows 的檔案鎖定 |
| `env.platforms.choose_platform` | 各平台 property 名稱（`Precision`、`DeviceIndex`）、HIP 平台名稱 |
| `env.doctor.benchmark` | PME 水盒以程式建構；約束與 exception 設定需實測 |
| `build.receptor.prepare_receptor` | PDBFixer 缺失 loop 篩選邏輯（`missingResidues` 鍵為 (chain index, residue index)） |
| `build.ligand` | `AssignBondOrdersFromTemplate` 對 PDBQT 的容錯；OpenFF NAGL 模型名稱與 wrapper API 隨版本變動 **[最需驗證]**；`vacuum_smoke_test` 的 ForceField 註冊 |
| `build.assemble` | `Modeller.addSolvent(boxShape=…)`、配體 chain/resname 設定、總電荷計算 |
| `tests/test_openmm_integration.py` | 水盒 fixture 用 `Modeller.addSolvent(boxSize=…)` 於空拓撲 |
| `build.protonation` | pdb2pqr CLI 參數與 .pka 檔格式（PROPKA 3.x）；尚未接入 `prepare_receptor`（M2） |

## C. 設計上已知未完成（M1 之後）

- GUI（NiceGUI）、Dimorphite-DL、ProLIF、P2Rank、膜與醣、多 replica 彙總、SMD 執行器、MM/GBSA、TI 玩具系統、docking 分冊移植、工作站佇列。
- Windows 安裝器 `installer/install.ps1` 未在 Windows 實測（micromamba 下載路徑與 tar 解壓）。
- `environment/*.yml` 尚未鎖定精確版本；第一次在各 OS 成功建立後請匯出 lock。

## 驗證指令（在你的機器）

```bash
pytest -v                                   # 純 Python + OpenMM 整合測試（有 openmm 才會跑）
md20 doctor                                 # 看平台階梯與 ns/day
md20 demo                                   # 合成後端完整流程
```
