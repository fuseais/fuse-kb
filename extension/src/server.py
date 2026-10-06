"""Entry point for the Fuse Knowledge Bases desktop extension.

Claude Desktop runs this with uv and passes the user's settings as
arguments. Unset optional settings can arrive as empty strings or as
unexpanded placeholders, so both are treated as "not set".
"""
import argparse
import os
import sys

# The bundle carries the fuse_kb package next to this file.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fuse_kb.library import KBLibrary  # noqa: E402
from fuse_kb.mcp_server import serve  # noqa: E402


def _setting(value):
    value = (value or "").strip()
    return None if not value or value.startswith("${") else value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="")
    parser.add_argument("--reranker", default="")
    parser.add_argument("--pgp-key-file", default="")
    args = parser.parse_args()

    if _setting(os.environ.get("FUSE_KB_PGP_PASSPHRASE")) is None:
        os.environ.pop("FUSE_KB_PGP_PASSPHRASE", None)

    folder = _setting(args.path)
    if folder:
        os.makedirs(os.path.expanduser(folder), exist_ok=True)
    library = KBLibrary(folder, reranker=_setting(args.reranker),
                        pgp_key_file=_setting(args.pgp_key_file))
    serve(library)


if __name__ == "__main__":
    main()
