"""Compound library for high-throughput pre-screening: Excel/CSV in, one 3D SDF per compound out.

Spec: docs/specs/hts_screen.md §1.  Pure Python except the optional RDKit post-download checks; the network
layer takes an injectable `fetch(url, headers) -> bytes` so every path is testable offline.

Source priority per row:  sdf > smiles > pubchem_cid > inchikey > chembl_id > ccd  (> name, only when allowed).
Everything is cached under <out_dir>/<name>.sdf and recorded in library_manifest.json; a re-run only fetches
what is missing.  A row that cannot be resolved is FAILED (with the reason), never silently dropped.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ..util import atomic_write_json, load_json, now_iso, safe_name, DecisionLog

COLUMN_ALIASES = {
    "name": {"name", "id", "compound", "ligand", "名稱", "化合物", "compound_name", "ligand_name"},
    "smiles": {"smiles", "smi", "canonical_smiles", "isomeric_smiles"},
    "pubchem_cid": {"pubchem_cid", "cid", "pubchem", "pubchemcid", "pubchem_id"},
    "inchikey": {"inchikey", "inchi_key", "standard_inchikey"},
    "chembl_id": {"chembl_id", "chembl", "chemblid"},
    "ccd": {"ccd", "pdb_ligand", "ligand_id", "het", "hetcode", "pdb_het", "ccd_id"},
    "sdf": {"sdf", "file", "path", "mol", "structure_file"},
}
SOURCE_PRIORITY = ("sdf", "smiles", "pubchem_cid", "inchikey", "chembl_id", "ccd")
USER_AGENT = "MD20-workstation/0.1 (HCC Lab NKUST; teaching; contact via GitHub fstcch-cmd/md20-workstation)"
PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
CHEMBL = "https://www.ebi.ac.uk/chembl/api/data/molecule"
RCSB_LIGAND = "https://files.rcsb.org/ligands/download"
_CID_RE = re.compile(r"^\d{1,10}$")
_INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
_CHEMBL_RE = re.compile(r"^CHEMBL\d+$", re.I)
_CCD_RE = re.compile(r"^[A-Za-z0-9]{1,5}$")


@dataclass
class LibraryEntry:
    name: str                      # safe file name (unique)
    label: str = ""                # name as written in the sheet
    smiles: str = ""
    pubchem_cid: str = ""
    inchikey: str = ""
    chembl_id: str = ""
    ccd: str = ""
    sdf: str = ""                  # local file given by the user
    row: int = 0                   # 1-based data row in the sheet (for error messages)

    def identifiers(self) -> list[str]:
        return [k for k in SOURCE_PRIORITY if getattr(self, k)]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LibraryFilters:
    min_heavy_atoms: int = 5
    max_heavy_atoms: int = 80
    min_mw: float = 100.0
    max_mw: float = 900.0
    strip_salts: bool = True
    dedupe: bool = True

    @classmethod
    def from_cfg(cls, d: dict | None) -> "LibraryFilters":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ----------------------------------------------------------------------------- reading the sheet
def _norm_col(c) -> str:
    return re.sub(r"[\s\-\.]+", "_", str(c).strip().lower())


def _canonical_columns(columns) -> dict[str, str]:
    """{sheet column → canonical field}; unknown columns are ignored."""
    out = {}
    for c in columns:
        n = _norm_col(c)
        for field_name, aliases in COLUMN_ALIASES.items():
            if n in aliases and field_name not in out.values():
                out[c] = field_name
                break
    return out


def read_library(path: Path | str, *, sheet: str | int | None = None) -> tuple[list[LibraryEntry], list[str]]:
    """Parse a compound sheet.  Returns (entries, problems); problems are human-readable and block the run."""
    import pandas as pd
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"找不到化合物庫檔案：{p}")
    suf = p.suffix.lower()
    if suf in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(p, sheet_name=sheet or 0, dtype=str)
    elif suf in (".csv", ".txt"):
        df = pd.read_csv(p, dtype=str, sep=None, engine="python", encoding="utf-8-sig")
    elif suf == ".tsv":
        df = pd.read_csv(p, dtype=str, sep="\t", encoding="utf-8-sig")
    else:
        raise ValueError(f"不支援的化合物庫格式 {suf}（接受 .xlsx/.xls/.csv/.tsv）")
    cols = _canonical_columns(df.columns)
    problems: list[str] = []
    if "name" not in cols.values():
        problems.append("缺少名稱欄（name / id / compound）。")
    if not any(v in SOURCE_PRIORITY for v in cols.values()):
        problems.append("沒有任何識別欄（smiles / pubchem_cid / inchikey / chembl_id / ccd / sdf）。")
    if problems:
        return [], problems
    df = df.rename(columns=cols)[list(dict.fromkeys(cols.values()))]
    entries: list[LibraryEntry] = []
    seen: dict[str, int] = {}
    for i, rec in enumerate(df.to_dict("records"), 1):
        vals = {k: ("" if v is None or (isinstance(v, float) and v != v) else str(v).strip()) for k, v in rec.items()}
        label = vals.get("name", "")
        if not label and not any(vals.get(k) for k in SOURCE_PRIORITY):
            continue                                    # blank line
        if not label:
            problems.append(f"第 {i} 列沒有名稱。")
            continue
        name = safe_name(label, fallback=f"cmpd_{i}")
        if name in seen:
            problems.append(f"第 {i} 列名稱「{label}」轉成檔名 {name} 後與第 {seen[name]} 列重複。")
            continue
        seen[name] = i
        e = LibraryEntry(name=name, label=label, row=i, **{k: vals.get(k, "") for k in SOURCE_PRIORITY})
        if e.pubchem_cid:
            e.pubchem_cid = e.pubchem_cid.split(".")[0]        # Excel turns 2332 into "2332.0"
            if not _CID_RE.match(e.pubchem_cid):
                problems.append(f"第 {i} 列 pubchem_cid「{e.pubchem_cid}」不是整數 CID。")
                continue
        if e.inchikey and not _INCHIKEY_RE.match(e.inchikey.upper()):
            problems.append(f"第 {i} 列 inchikey「{e.inchikey}」格式不對（14-10-1 大寫字母）。")
            continue
        if e.chembl_id and not _CHEMBL_RE.match(e.chembl_id):
            problems.append(f"第 {i} 列 chembl_id「{e.chembl_id}」格式不對（CHEMBL 開頭）。")
            continue
        if e.ccd and not _CCD_RE.match(e.ccd):
            problems.append(f"第 {i} 列 ccd「{e.ccd}」不是 PDB 配體代碼（1–5 個英數字）。")
            continue
        if e.sdf:
            sp = Path(e.sdf)
            e.sdf = str(sp if sp.is_absolute() else (p.parent / sp))
        if not e.identifiers():
            problems.append(f"第 {i} 列「{label}」沒有任何識別資料。")
            continue
        entries.append(e)
    if not entries and not problems:
        problems.append("化合物庫是空的。")
    return entries, problems


MANUAL_DIR = "manual_upload"
NAMING_RULES = (
    ("檔名要和表格「name」欄完全相同，再加上 .sdf。例如表格寫 caffeine，檔名就是 caffeine.sdf。"
     "只能用英文字母、數字、底線與連字號，不能有空格，最長 40 個字元。Windows 的檔案系統不分大小寫，"
     "所以表格裡不能有只差大小寫的名稱。一個檔案只放一個化合物。",
     "The file name must equal the sheet's \"name\" column plus .sdf. If the sheet says caffeine, the file is "
     "caffeine.sdf. Use letters, digits, underscore and hyphen only, with no spaces and at most 40 characters. "
     "Windows file systems ignore case, so the sheet must not contain names that differ only by case. Put one "
     "compound in each file.",
     "ファイル名は表の「name」列と完全に同じにし、.sdf を付けます。たとえば表に caffeine とあれば、ファイル名は "
     "caffeine.sdf です。使える文字は英字、数字、アンダースコア、ハイフンだけで、空白は使えず、最大 40 文字です。"
     "Windows のファイルシステムは大文字と小文字を区別しないため、大文字と小文字だけが違う名前を表に入れないでください。"
     "1 つのファイルには 1 つの化合物だけを入れます。",
     "파일 이름은 표의 \"name\" 열과 똑같이 하고 .sdf를 붙입니다. 예를 들어 표에 caffeine이라고 쓰면 파일 이름은 "
     "caffeine.sdf입니다. 영문자, 숫자, 밑줄, 하이픈만 쓸 수 있고 공백은 안 되며 최대 40자입니다. Windows 파일 "
     "시스템은 대소문자를 구분하지 않으므로 대소문자만 다른 이름이 표에 있으면 안 됩니다. 파일 하나에는 화합물 하나만 "
     "넣습니다."),
)
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _manual_file(out_dir: Path, name: str) -> Path | None:
    """The manual upload for a sheet name, matched case-insensitively (as the Windows file system does)."""
    d = Path(out_dir) / MANUAL_DIR
    if not d.is_dir():
        return None
    want = f"{name}.sdf".lower()
    return next((x for x in d.iterdir() if x.is_file() and x.name.lower() == want), None)


def manual_upload_report(names: list[str], out_dir: Path | str) -> dict:
    """Which manual SDF uploads match the sheet: matched, still missing, files that break the naming rule or match no
    row (never used, so a misnamed file cannot stand in for another compound), and sheet names that differ only by
    case (they would share one file on Windows)."""
    d = Path(out_dir) / MANUAL_DIR
    files = sorted(x.name for x in d.glob("*")) if d.is_dir() else []
    wanted = {f"{n}.sdf".lower(): n for n in names}
    bad_name = [f for f in files if not (f.lower().endswith(".sdf") and _NAME_RE.match(f[:-4]))]
    matched = [wanted[f.lower()] for f in files if f.lower() in wanted and f not in bad_name]
    unmatched = [f for f in files if f.lower() not in wanted and f not in bad_name]
    seen, conflicts = {}, []
    for n in names:
        k = n.lower()
        if k in seen and seen[k] != n:
            conflicts.append([seen[k], n])
        seen.setdefault(k, n)
    return {"dir": str(d), "matched": matched, "missing": [n for n in names if n not in matched],
            "bad_name": bad_name, "unmatched": unmatched, "case_conflicts": conflicts, "rules": NAMING_RULES[0]}


def check_upload_name(filename: str, names: list[str]) -> tuple[bool, tuple[str, str, str, str], str | None]:
    """GUI upload check: (ok, (zh, en, ja, ko) reason, file name to save as — the sheet's own spelling)."""
    stem, ext = (filename[:-4], filename[-4:]) if len(filename) > 4 else (filename, "")
    if ext.lower() != ".sdf":
        return False, ("只接受 .sdf 檔。", "Only .sdf files are accepted.", "受け付けるのは .sdf ファイルだけです。",
                       ".sdf 파일만 받습니다."), None
    if not _NAME_RE.match(stem):
        return False, ("檔名只能用英文字母、數字、底線與連字號，最長 40 個字元。",
                       "Use only letters, digits, underscore and hyphen, at most 40 characters.",
                       "ファイル名に使えるのは英字、数字、アンダースコア、ハイフンだけで、最大 40 文字です。",
                       "파일 이름에는 영문자, 숫자, 밑줄, 하이픈만 쓸 수 있으며 최대 40자입니다."), None
    hits = [n for n in names if n.lower() == stem.lower()]
    if not hits:
        return False, (f"表格中沒有名為 {stem} 的化合物。", f"No compound named {stem} in the sheet.",
                       f"表に {stem} という名前の化合物はありません。", f"표에 이름이 {stem}인 화합물이 없습니다."), None
    if len(hits) > 1:
        return False, (f"表格中有只差大小寫的名稱（{'、'.join(hits)}），請先在表格裡改名。",
                       f"The sheet has names that differ only by case ({', '.join(hits)}). Rename them in the sheet first.",
                       f"表に大文字と小文字だけが違う名前があります（{'、'.join(hits)}）。先に表で名前を変えてください。",
                       f"표에 대소문자만 다른 이름이 있습니다({', '.join(hits)}). 먼저 표에서 이름을 바꾸십시오."), None
    return True, ("", "", "", ""), f"{hits[0]}.sdf"


TEMPLATE_ROWS = [   # D-79: every row works offline (SMILES only), so the example runs as uploaded
    ("benzamidine", "NC(=N)c1ccccc1"),
    ("4-aminobenzamidine", "NC(=N)c1ccc(N)cc1"),
    ("4-methylbenzamidine", "Cc1ccc(C(N)=N)cc1"),
    ("3-aminobenzamidine", "NC(=N)c1cccc(N)c1"),
    ("benzylamine", "NCc1ccccc1"),
    ("aspirin", "CC(=O)Oc1ccccc1C(=O)O"),
    ("caffeine", "Cn1cnc2c1c(=O)n(C)c(=O)n2C"),
    ("phenol", "Oc1ccccc1"),
]
TEMPLATE_HELP = [
    ("欄位 Column", "說明 Meaning", "例 Example"),
    ("name", "必填。化合物名稱，用英數字。Required. Letters and digits.", "aspirin"),
    ("smiles", "化學結構，不需網路。Structure; no network needed.", "CC(=O)Oc1ccccc1C(=O)O"),
    ("pubchem_cid", "沒有 SMILES 時，從 PubChem 下載（需要網路）。Downloaded from PubChem when there is no SMILES.", "2244"),
    ("inchikey", "同上，以 InChIKey 查 PubChem。Looked up in PubChem.", "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"),
    ("chembl_id", "同上，從 ChEMBL 下載。Downloaded from ChEMBL.", "CHEMBL25"),
    ("ccd", "同上，PDB 的三字母配體代碼。PDB ligand code.", "AIN"),
    ("sdf", "自己的結構檔，檔名必須是 name 加 .sdf，於介面「手動上傳結構」上傳。Your own file, named <name>.sdf.", "aspirin.sdf"),
    ("", "每列只需填一種結構來源；同一列填了好幾種時，優先序 sdf > smiles > pubchem_cid > inchikey > chembl_id > ccd。"
         "Fill one structure source per row; when several are filled, sdf comes first, then the order above.", ""),
    ("", "範例的第一張工作表可以直接上傳試跑（3PTB 胰蛋白酶：前四個是苯甲脒類抑制劑，後四個是對照）。"
         "The first sheet can be uploaded as is (trypsin 3PTB: four benzamidine-type inhibitors and four controls).", ""),
]


def write_template(path: Path | str) -> Path:
    """Example compound table (xlsx or csv by extension).  D-79: the first sheet runs as uploaded — SMILES only, so no
    network lookup can fail and no missing SDF stops the screen; the other ways to name a compound are explained on a
    second sheet ("說明 How to fill"), which the reader ignores (it reads the first sheet)."""
    import pandas as pd
    cols = ["name", "smiles", "pubchem_cid", "inchikey", "chembl_id", "ccd", "sdf"]
    df = pd.DataFrame([{**{c: "" for c in cols}, "name": n, "smiles": smi} for n, smi in TEMPLATE_ROWS], columns=cols)
    p = Path(path)
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        with pd.ExcelWriter(p) as xw:
            df.to_excel(xw, index=False, sheet_name="compounds")
            pd.DataFrame(TEMPLATE_HELP[1:], columns=list(TEMPLATE_HELP[0])).to_excel(xw, index=False, sheet_name="說明 How to fill")
    else:
        df.to_csv(p, index=False, encoding="utf-8-sig")
    return p


# ----------------------------------------------------------------------------- network layer
class RateLimiter:
    """Simple token bucket shared by threads (PubChem asks for ≤ 5 requests/s; we use 4)."""

    def __init__(self, per_second: float = 4.0):
        self.interval = 1.0 / max(per_second, 0.1)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next:
                time.sleep(self._next - now)
                now = time.monotonic()
            self._next = now + self.interval


class FetchError(RuntimeError):
    def __init__(self, msg: str, *, status: int | None = None, retry_after: float | None = None):
        super().__init__(msg)
        self.status, self.retry_after = status, retry_after


def http_fetch(url: str, headers: dict | None = None, *, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        ra = exc.headers.get("Retry-After") if exc.headers else None
        raise FetchError(f"HTTP {exc.code} {url}", status=exc.code,
                         retry_after=float(ra) if ra and ra.replace(".", "", 1).isdigit() else None) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"{type(exc).__name__}: {exc} ({url})") from exc


def fetch_with_retry(fetch, url: str, *, headers: dict | None = None, retries: int = 3, limiter: RateLimiter | None = None,
                     sleep=time.sleep) -> bytes:
    """Retry on 429/5xx/network errors with exponential back-off; 4xx (not 429) fail at once."""
    delay = 1.0
    last: Exception | None = None
    for attempt in range(retries + 1):
        if limiter:
            limiter.wait()
        try:
            return fetch(url, {"User-Agent": USER_AGENT, **(headers or {})})
        except FetchError as exc:
            last = exc
            if exc.status is not None and 400 <= exc.status < 500 and exc.status != 429:
                raise
            if attempt == retries:
                break
            sleep(exc.retry_after if exc.retry_after else delay)
            delay *= 2
    raise FetchError(f"重試 {retries} 次後仍失敗：{last}", status=getattr(last, "status", None))


# ----------------------------------------------------------------------------- resolvers
def _q(s: str) -> str:
    return urllib.parse.quote(str(s), safe="")


def _pubchem_sdf(fetch, cid: str, limiter, sleep) -> tuple[bytes, str]:
    try:
        return fetch_with_retry(fetch, f"{PUBCHEM}/compound/cid/{_q(cid)}/SDF?record_type=3d", limiter=limiter, sleep=sleep), "pubchem-3d"
    except FetchError as exc:
        if exc.status != 404:
            raise
    # no 3D conformer on PubChem (large/flexible/inorganic): take the 2D record, RDKit builds 3D later
    return fetch_with_retry(fetch, f"{PUBCHEM}/compound/cid/{_q(cid)}/SDF", limiter=limiter, sleep=sleep), "pubchem-2d"


def _pubchem_cid_from_inchikey(fetch, key: str, limiter, sleep) -> str:
    raw = fetch_with_retry(fetch, f"{PUBCHEM}/compound/inchikey/{_q(key.upper())}/cids/JSON", limiter=limiter, sleep=sleep)
    cids = (json.loads(raw.decode("utf-8")).get("IdentifierList") or {}).get("CID") or []
    if not cids:
        raise FetchError(f"PubChem 沒有 InChIKey {key}")
    return str(cids[0])


def _pubchem_cid_from_name(fetch, name: str, limiter, sleep) -> str:
    raw = fetch_with_retry(fetch, f"{PUBCHEM}/compound/name/{_q(name)}/cids/JSON", limiter=limiter, sleep=sleep)
    cids = (json.loads(raw.decode("utf-8")).get("IdentifierList") or {}).get("CID") or []
    if not cids:
        raise FetchError(f"PubChem 以名稱「{name}」查不到化合物")
    return str(cids[0])


def _chembl_smiles(fetch, cid: str, limiter, sleep) -> str:
    raw = fetch_with_retry(fetch, f"{CHEMBL}/{_q(cid.upper())}.json", limiter=limiter, sleep=sleep)
    d = json.loads(raw.decode("utf-8"))
    smi = ((d.get("molecule_structures") or {}).get("canonical_smiles")) or ""
    if not smi:
        raise FetchError(f"ChEMBL {cid} 沒有 canonical_smiles（可能是生物製劑或多成分）")
    return smi


def _ccd_sdf(fetch, code: str, limiter, sleep) -> bytes:
    return fetch_with_retry(fetch, f"{RCSB_LIGAND}/{_q(code.upper())}_ideal.sdf", limiter=limiter, sleep=sleep)


def _smiles_to_sdf_text(smiles: str, name: str) -> str:
    """3D embedding identical to dock()._ligand_mol so the screen and the final docking see the same molecule."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"無法解析 SMILES：{smiles}")
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3(); params.randomSeed = 2026
    if AllChem.EmbedMolecule(mol, params) != 0 and AllChem.EmbedMolecule(mol, randomSeed=2026, useRandomCoords=True) != 0:
        raise ValueError("RDKit 無法產生 3D 構形")
    try:
        AllChem.MMFFOptimizeMolecule(mol, maxIters=2000)
    except Exception:  # noqa: BLE001
        AllChem.UFFOptimizeMolecule(mol, maxIters=2000)
    mol.SetProp("_Name", name)
    return Chem.MolToMolBlock(mol) + "$$$$\n"


def _rdkit_available() -> bool:
    try:
        import rdkit  # noqa: F401
        return True
    except ImportError:
        return False


def _check_sdf(path: Path, filters: LibraryFilters, decisions: DecisionLog | None, name: str) -> dict:
    """Parse, strip salts, apply size filters.  Returns facts for the manifest; raises on unusable input."""
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors
    mols = [m for m in Chem.SDMolSupplier(str(path), removeHs=False) if m is not None]
    if not mols:
        raise ValueError("SDF 無法解析（RDKit 拒絕）")
    mol = mols[0]
    facts: dict = {"checked": True, "salt_stripped": False}
    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True)
    if len(frags) > 1:
        if not filters.strip_salts:
            raise ValueError(f"含 {len(frags)} 個片段（鹽或溶劑），而 filters.strip_salts=false")
        big = max(frags, key=lambda m: m.GetNumHeavyAtoms())
        dropped = [Chem.MolToSmiles(Chem.RemoveHs(f)) for f in frags if f is not big]
        if decisions:
            decisions.record("screen.library", name, "largest fragment kept",
                             f"輸入含 {len(frags)} 個片段，只保留最大的片段對接，移除了 {', '.join(dropped)}。"
                             "如果這是季銨鹽或金屬配合物這類需要保留反離子的分子，請改提供去鹽後的 SDF。")
        mol = big
        if mol.GetNumConformers() == 0 or not mol.GetConformer().Is3D():
            raise ValueError("去鹽後沒有 3D 座標")
        mol.SetProp("_Name", name)
        w = Chem.SDWriter(str(path)); w.write(mol); w.close()
        facts["salt_stripped"] = True
    heavy = mol.GetNumHeavyAtoms()
    mw = float(Descriptors.MolWt(mol))
    facts.update({"heavy_atoms": int(heavy), "mw": round(mw, 2), "inchikey": Chem.MolToInchiKey(mol),
                  "smiles": Chem.MolToSmiles(Chem.RemoveHs(mol)), "charge": int(Chem.GetFormalCharge(mol)),
                  "rotatable_bonds": int(rdMolDescriptors.CalcNumRotatableBonds(mol))})
    if not (filters.min_heavy_atoms <= heavy <= filters.max_heavy_atoms):
        facts["skip"] = f"重原子數 {heavy} 不在 {filters.min_heavy_atoms}–{filters.max_heavy_atoms}（screen.filters 可調）"
    elif not (filters.min_mw <= mw <= filters.max_mw):
        facts["skip"] = f"分子量 {mw:.0f} 不在 {filters.min_mw:.0f}–{filters.max_mw:.0f}（screen.filters 可調）"
    if not mol.GetConformer().Is3D():
        # 2D record (PubChem fallback / CCD without ideal coords): rebuild 3D from the connectivity
        text = _smiles_to_sdf_text(facts["smiles"], name)
        path.write_text(text, encoding="utf-8")
        facts["rebuilt_3d"] = True
    return facts


# ----------------------------------------------------------------------------- main
def resolve_library(entries: list[LibraryEntry], out_dir: Path | str, *, fetch=http_fetch, filters: LibraryFilters | None = None,
                    allow_name_lookup: bool = False, decisions: DecisionLog | None = None, progress_cb=None,
                    workers: int = 4, sleep=time.sleep, limiter: RateLimiter | None = None) -> dict:
    """Fetch/build one SDF per entry into out_dir.  Returns the manifest (also written to library_manifest.json).

    manifest["entries"][name] = {status: OK|FAILED|SKIPPED, source, path, error, heavy_atoms, mw, inchikey, …}
    Existing OK entries (file present) are reused without any network access.
    """
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    mpath = out / "library_manifest.json"
    manifest = load_json(mpath, {"entries": {}})
    manifest.setdefault("entries", {})
    filters = filters or LibraryFilters()
    limiter = limiter or RateLimiter(4.0)
    have_rdkit = _rdkit_available()
    lock = threading.Lock()
    todo = [e for e in entries if not (manifest["entries"].get(e.name, {}).get("status") == "OK"
                                       and Path(manifest["entries"][e.name].get("path", "")).is_file())]
    done = {"n": len(entries) - len(todo)}

    def one(e: LibraryEntry) -> dict:
        rec: dict = {"label": e.label, "row": e.row, "identifiers": {k: getattr(e, k) for k in e.identifiers()}}
        dst = out / f"{e.name}.sdf"
        try:
            src, data, note = None, None, ""
            manual = _manual_file(out, e.name)
            if manual is not None:
                # manual upload (D-50): wins over any download, so a blocked network never blocks the screen
                data, src = manual.read_bytes(), "manual-upload"
            elif e.sdf:
                sp = Path(e.sdf)
                if not sp.is_file():
                    raise FileNotFoundError(f"找不到 SDF {sp}")
                data, src = sp.read_bytes(), "local-sdf"
            elif e.smiles:
                if not have_rdkit:
                    raise RuntimeError("SMILES 需要 RDKit 產生 3D 構形（本機未安裝）")
                data, src = _smiles_to_sdf_text(e.smiles, e.name).encode("utf-8"), "smiles-rdkit"
            elif e.pubchem_cid:
                data, src = _pubchem_sdf(fetch, e.pubchem_cid, limiter, sleep)
            elif e.inchikey:
                cid = _pubchem_cid_from_inchikey(fetch, e.inchikey, limiter, sleep)
                data, src = _pubchem_sdf(fetch, cid, limiter, sleep)
                rec["pubchem_cid"] = cid
            elif e.chembl_id:
                smi = _chembl_smiles(fetch, e.chembl_id, limiter, sleep)
                if not have_rdkit:
                    raise RuntimeError("ChEMBL 只給 SMILES，需要 RDKit 產生 3D 構形（本機未安裝）")
                data, src, rec["smiles_from_chembl"] = _smiles_to_sdf_text(smi, e.name).encode("utf-8"), "chembl-smiles-rdkit", smi
            elif e.ccd:
                data, src = _ccd_sdf(fetch, e.ccd, limiter, sleep), "rcsb-ccd-ideal"
            elif allow_name_lookup and e.label:
                cid = _pubchem_cid_from_name(fetch, e.label, limiter, sleep)
                data, src = _pubchem_sdf(fetch, cid, limiter, sleep)
                rec["pubchem_cid"] = cid
                note = f"以名稱「{e.label}」查 PubChem 得到 CID {cid}。名稱查詢可能對到錯的分子，請核對。"
                if decisions:
                    decisions.record("screen.library", e.name, f"name lookup → CID {cid}", note, kind="human")
            else:
                raise ValueError("沒有識別資料（名稱查詢預設關閉：screen.allow_name_lookup）")
            if not data or len(data) < 20:
                raise ValueError(f"{src} 回傳空內容")
            dst.write_bytes(data)
            rec.update({"source": src, "path": str(dst), "checked": False})
            if note:
                rec["note"] = note
            if have_rdkit:
                facts = _check_sdf(dst, filters, decisions, e.name)
                rec.update(facts)
                if facts.get("skip"):
                    rec["status"], rec["error"] = "SKIPPED", facts["skip"]
                    return rec
            rec["status"] = "OK"
        except Exception as exc:  # noqa: BLE001  — recorded per compound, never aborts the library
            rec["status"], rec["error"] = "FAILED", f"{type(exc).__name__}: {exc}"
            if dst.is_file():
                try:
                    dst.unlink()
                except OSError:
                    pass
        return rec

    def _store(e: LibraryEntry, rec: dict) -> None:
        with lock:
            rec["at"] = now_iso()
            manifest["entries"][e.name] = rec
            done["n"] += 1
            atomic_write_json(manifest, mpath)
            if progress_cb:
                progress_cb({"stage": "screen_library", "ligand": e.name, "i": done["n"], "n": len(entries), "status": rec["status"]})

    if workers > 1 and len(todo) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for e, rec in zip(todo, ex.map(one, todo)):
                _store(e, rec)
    else:
        for e in todo:
            _store(e, one(e))

    # duplicates by InChIKey (only when every entry was checked)
    if filters.dedupe and have_rdkit:
        seen: dict[str, str] = {}
        for e in entries:
            rec = manifest["entries"].get(e.name) or {}
            if rec.get("status") != "OK" or not rec.get("inchikey"):
                continue
            k = rec["inchikey"]
            if k in seen and seen[k] != e.name:
                rec["status"], rec["error"] = "SKIPPED", f"與 {seen[k]} 是同一分子（InChIKey 相同），只對接一次"
                rec["duplicate_of"] = seen[k]
            else:
                seen.setdefault(k, e.name)
    manifest["order"] = [e.name for e in entries]
    manifest["summary"] = library_summary(manifest)
    manifest["updated_at"] = now_iso()
    atomic_write_json(manifest, mpath)
    if decisions:
        s = manifest["summary"]
        decisions.record("screen.library", "resolve", s,
                         f"化合物庫共 {s['total']} 筆，可用 {s['OK']}、失敗 {s['FAILED']}、略過 {s['SKIPPED']}。"
                         "失敗或略過的化合物不會悄悄消失，會列在篩選閘門與報告裡。")
    return manifest


def library_summary(manifest: dict) -> dict:
    c = {"OK": 0, "FAILED": 0, "SKIPPED": 0}
    for r in manifest.get("entries", {}).values():
        c[r.get("status", "FAILED")] = c.get(r.get("status", "FAILED"), 0) + 1
    c["total"] = sum(c.values())
    return c


def usable_entries(manifest: dict) -> list[dict]:
    order = manifest.get("order") or list(manifest.get("entries", {}))
    return [{"name": n, **manifest["entries"][n]} for n in order if manifest["entries"].get(n, {}).get("status") == "OK"]


def problem_entries(manifest: dict) -> list[dict]:
    order = manifest.get("order") or list(manifest.get("entries", {}))
    return [{"name": n, **manifest["entries"][n]} for n in order if manifest["entries"].get(n, {}).get("status") != "OK"]
