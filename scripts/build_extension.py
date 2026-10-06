"""Build dist/fuse-kb.mcpb, the Claude Desktop extension.

An .mcpb file is a zip with manifest.json at its root. This copies the
extension files and the fuse_kb package into a staging folder and zips it;
no Node.js tooling needed.

    python scripts/build_extension.py
"""
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
PACKAGE = ROOT / "src" / "fuse_kb"
OUT = ROOT / "dist" / "fuse-kb.mcpb"


def main() -> int:
    manifest = json.loads((EXT / "manifest.json").read_text())
    version = (PACKAGE / "__init__.py").read_text().split('__version__ = "')[1].split('"')[0]
    if manifest["version"] != version:
        print(f"manifest version {manifest['version']} != fuse_kb {version}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        shutil.copy(EXT / "manifest.json", stage)
        shutil.copy(EXT / "pyproject.toml", stage)
        shutil.copytree(EXT / "src", stage / "src")
        shutil.copytree(PACKAGE, stage / "src" / "fuse_kb",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for extra in ("LICENSE", "NOTICE"):
            shutil.copy(ROOT / extra, stage)
        if (EXT / "icon.png").exists():
            shutil.copy(EXT / "icon.png", stage)

        OUT.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    z.write(path, path.relative_to(stage).as_posix())
    print(f"Built {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
