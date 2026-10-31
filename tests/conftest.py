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
