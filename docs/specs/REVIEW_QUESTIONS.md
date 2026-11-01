# 最希望審查者挑戰的設計決定（依重要性）

1. **約束／凍結／截斷（設計中，最該在實作前審查）**——[restraints_freeze_truncation.md](restraints_freeze_truncation.md)
   - 前提「OpenMM 凍結不省運算、省資源要靠截斷」是否正確且完整？
   - 截斷模型（R = 12 Å、ACE/NME 帽、4 Å 約束殼層）的可信度與預設值；截斷後做 SMD/umbrella 是否應禁止？
   - 分組分階段約束的預設數值，與藥廠常見 protocol 的差距。
2. **傘狀採樣補窗**——[umbrella_adaptive.md](umbrella_adaptive.md)
   - 連續性判準（合併直方圖 < 中位數 10%）與目標重疊 0.2；
   - k 選擇規則（漂移 ≤ 2σ）與中心預偏移上限（自動 1σ／手動 3σ）的理論依據；
   - 補不起來時（能障比 k_max 陡）的後備方案。
3. **金屬鍵結模型**——[metal_sites.md](metal_sites.md)
   - 1-2/1-3 排除 + 1-4 縮放 + M–D–X 角是否等同 MCPB.py 的處理？金屬 LJ 是否也要換？
   - Hessian → 內座標力常數用 Wilson-B pseudo-inverse 的合理性。
4. **ΔG° 的嚴謹度**——一維 COM 距離 PMF + 徑向積分，未做方向／構形限制校正；research tier 才輸出且需 ≥3 replica 與半段收斂。
   是否應改成 Woo & Roux 式的限制 + 解除校正？
5. **教學與誠實的平衡**——哪些近似應該在 GUI 上更醒目（例如互作只看距離、vdW 表面、截斷模型）？

回饋方式：直接在對應文件的「想請審查者回答」下方寫建議，或彙整成一份 prompt 交給下一個開發 session。
