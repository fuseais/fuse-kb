"""The Claude Desktop extension bundle stays in sync with the package."""
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from fuse_kb import KBLibrary, Toolkit, __version__

ROOT = Path(__file__).resolve().parent.parent


def test_bundle_builds_with_manifest_at_root():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_extension.py")],
                   check=True, capture_output=True)
    names = zipfile.ZipFile(ROOT / "dist" / "fuse-kb.mcpb").namelist()
    assert "manifest.json" in names and "src/server.py" in names
    assert "src/fuse_kb/mcp_server.py" in names and "LICENSE" in names
    assert not any("__pycache__" in n for n in names)


def test_manifest_matches_package(kb_dir):
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text())
    assert manifest["version"] == __version__
    listed = {t["name"] for t in manifest["tools"]}
    offered = {t["name"] for t in Toolkit(KBLibrary(kb_dir, embedder=None)).definitions()}
    assert listed == offered
