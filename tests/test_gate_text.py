"""D-55: every gate created in the code has an English title and general explanation; options translate."""
import re
from pathlib import Path

from md20.gui.gate_text import gate_title, gate_general, option_text, GATES


def test_every_gate_name_in_the_code_is_covered():
    names = set()
    for f in Path("md20").rglob("*.py"):
        txt = f.read_text(encoding="utf-8")
        names |= set(re.findall(r'Gate\("([^"{]+)"', txt))
        names |= {n.split("{")[0].strip() for n in re.findall(r'Gate\(f"([^"]+)"', txt)}
        names |= set(re.findall(r'"name": "([^"]+)", "status": "NEEDS_HUMAN"', txt))
    missing = [n for n in names if not gate_general(n) and n not in GATES]
    assert not missing, missing


def test_titles_and_options():
    assert gate_title("metal ZN:A262", "en") == "Metal site ZN:A262" and gate_title("metal ZN:A262", "zh") == "金屬位點 ZN:A262"
    assert gate_title("metal charges ZN:A1", "en").startswith("Metal-site charges")
    assert option_text("截斷（加 ACE/NME 端帽）", "en") == "Truncate (add ACE and NME caps)"
    assert option_text("仍要使用（structure_override.resolution）", "en") == "Use anyway"
    assert option_text("box.from_residue: BEN", "en") == "Define the box from residue BEN"
    assert option_text("metal_policy: {ZN: bonded}（晶體幾何鍵結模型）", "en") == "Metal model: ZN: bonded"
    assert option_text("截斷（加 ACE/NME 端帽）", "zh") == "截斷（加 ACE/NME 端帽）"
    assert option_text("something new", "en") == "something new"
