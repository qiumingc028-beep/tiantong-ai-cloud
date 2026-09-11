"""Linux-only installer execution checks; collected by the Linux full suite."""
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
LINUX = (ROOT / "ops" / "install_r297_trusted_linux_host.sh").read_text(encoding="utf-8")


def test_linux_fixed_sha_install_has_complete_import_closure(tmp_path):
    files = re.search(r"broker_files=\((.*?)\)", LINUX, re.S).group(1).split()
    assert '"${broker_files[@]}"' in LINUX
    (tmp_path / "ops").mkdir()
    for name in files:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, tmp_path / name)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from ops.r297_evidence_broker import EvidenceBroker; "
            "from ops.r297_broker_client import peer_uid",
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
