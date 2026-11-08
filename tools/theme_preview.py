import sys; import os,sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md20.gui import theme
G=theme.gate_state
def card(mod,glyph,badge,title,body,opts=""):
    return f'''<div class="q-card md20-gate md20-gate--{mod}"><div class="row"><span class="md20-glyph">{glyph}</span>
<span class="q-badge" style="background:var(--md20-{ 'needs' if mod=='needs' else 'autofix' if mod=='autofix' else 'pass'});color:#fff">{badge}</span>
<span class="md20-section" style="margin:0">{title}</span></div><div class="md20-why" style="margin-top:6px">{body}</div>{opts}</div>'''
html=f'''<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MD20 介面設計</title>{theme.css("zh")}
<style>body{{margin:0;padding:0}} .wrap{{max-width:var(--md20-width);margin:0 auto;padding:0 20px 48px}}
.row{{display:flex;align-items:center;gap:8px}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.q-card{{padding:18px 20px;margin-bottom:14px}} .hdr{{display:flex;align-items:center;justify-content:space-between}}
.btn{{display:inline-block;background:var(--md20-primary);color:#fff;border-radius:6px;padding:8px 16px;font-weight:600;font-size:13.5px}}
.btn.ghost{{background:transparent;color:var(--md20-primary);border:1px solid var(--md20-primary)}}
.sw{{height:40px;border-radius:6px;border:1px solid var(--md20-line)}} th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid var(--md20-line);font-size:13.5px}}
th{{background:#F7FAFA;color:var(--md20-ink-muted);font-size:12.5px;font-weight:600}}</style></head>
<body><header class="md20-header hdr" style="height:56px;display:flex"><div class="wrap hdr" style="width:100%;padding-top:0;padding-bottom:0">
<span class="md20-title text-lg">MD20 分子模擬工作站</span><span class="row" style="gap:16px"><a href="#" style="color:var(--md20-ink);text-decoration:none">首頁</a><a href="#" style="color:var(--md20-ink);text-decoration:none">電腦狀態</a><span class="md20-muted">繁體中文</span></span></div></header>
<div class="wrap">
<div class="md20-running row" style="padding:10px 16px;margin:16px 0;border-radius:8px"><span class="md20-pulse"></span><span class="text-sm" style="margin-left:8px">計算進行中：trypsin_demo · 傘狀採樣 window 7/12</span></div>
<h1 class="text-2xl" style="margin:.4em 0 .1em">MD20 分子模擬工作站</h1>
<p class="md20-muted">從分子對接、分子動力學一路做到結合自由能。每一步都會先檢查輸入；程式自動修正的地方會說明改了什麼，需要你判斷的地方流程會停下來並列出可選的做法。</p>
<h2 class="md20-section">選擇工作模式</h2>
<div class="grid">
<div class="q-card md20-mode"><div class="md20-section" style="margin:0">教學模式一：多個小分子</div><p class="md20-why">六個代謝物同時對接 NF-κB p65，學多配體對接、檢查結構與複合物穩定性。</p><a class="btn" href="#">開啟</a></div>
<div class="q-card md20-mode"><div class="md20-section" style="margin:0">專業模式</div><p class="md20-why">每個參數都可調整；數值先從依案例建議開始，改的每個值都即時檢查是否合理。</p><a class="btn ghost" href="#">開啟</a></div></div>
<h2 class="md20-section" style="margin-top:28px">閘門（三態）</h2>
{card("needs","◆","需要你決定","結構可信度 · 解析度","解析度 3.4 Å。較低解析度的座標不確定性較高，是否仍要使用由你決定。",'<div style="margin-top:8px"><span class="text-sm" style="color:var(--md20-primary)">• 換一個更高解析度的結構</span><br><span class="text-sm" style="color:var(--md20-primary)">• 仍要使用（structure_override.resolution）</span></div>')}
{card("autofix","◐","已自動修正","組裝 · 金屬位點 ZN:C1","晶體配位水保留為第四個鍵結配位（D-133），配位數與晶體一致。已寫進決策日誌。")}
{card("pass","●","通過","水盒 · 尺寸","拉離距離加餘裕後仍小於半個水盒邊長，可以進行傘狀採樣。")}
<h2 class="md20-section" style="margin-top:28px">結合自由能結果</h2>
<div class="q-card" style="padding:0"><table style="width:100%;border-collapse:collapse"><tr><th>配體</th><th>ΔPMF (kJ mol⁻¹)</th><th>ΔG° (kJ mol⁻¹)</th><th>結合距離 (nm)</th><th>重複</th></tr>
<tr><td>BEN</td><td>58.2 ± 3.1</td><td>−26.4 ± 2.0</td><td>0.182</td><td>3</td></tr>
<tr><td>CDA</td><td>41.7 ± 5.5</td><td>−18.9（徑向近似，不用於排序）</td><td>0.204</td><td>3</td></tr></table></div>
<h2 class="md20-section" style="margin-top:28px">調色盤</h2>
<div class="grid" style="grid-template-columns:repeat(4,1fr)">
{"".join(f'<div><div class="sw" style="background:{v}"></div><div class="text-xs" style="margin-top:4px">{k} {v}</div></div>' for k,v in theme.PALETTE.items())}
</div></div></body></html>'''
import sys as _s; open(_s.argv[1] if len(_s.argv)>1 else 'md20_theme.html','w',encoding='utf-8').write(html)
print("ok")
