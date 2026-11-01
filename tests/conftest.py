import urllib.request

import pytest


@pytest.fixture(scope="session")
def pdb_3ptb(tmp_path_factory):
    """Bovine trypsin + benzamidine (3PTB).  Downloaded once per session; skips offline."""
    d = tmp_path_factory.mktemp("rcsb")
    p = d / "3PTB.pdb"
    try:
        urllib.request.urlretrieve("https://files.rcsb.org/download/3PTB.pdb", p)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"RCSB unreachable: {exc}")
    return p


@pytest.fixture(scope="session")
def pdb_ca2(tmp_path_factory):
    """Human carbonic anhydrase II (3KS3): Zn bound by His94/His96/His119 + water.  Skips offline."""
    d = tmp_path_factory.mktemp("rcsb_ca2")
    p = d / "3KS3.pdb"
    try:
        urllib.request.urlretrieve("https://files.rcsb.org/download/3KS3.pdb", p)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"RCSB unreachable: {exc}")
    return p
