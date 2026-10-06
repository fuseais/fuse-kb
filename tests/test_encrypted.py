"""PGP-encrypted KB files, against a real GnuPG with throwaway keyrings."""
import glob
import os
import shutil
import subprocess

import pytest

from fuse_kb import FuseKBError, KBLibrary, KnowledgeBase
from fuse_kb.cli import main

from conftest import build_kb

GPG = shutil.which("gpg") or shutil.which("gpg2")
pytestmark = pytest.mark.skipif(GPG is None, reason="GnuPG not installed")
PASS = "correct horse battery staple"


def _gpg(home, *args, stdin=None):
    return subprocess.run([GPG, "--homedir", str(home), "--batch", *args],
                          input=stdin, capture_output=True, check=True).stdout


def _make_key(home, email):
    home.mkdir(mode=0o700)
    _gpg(home, "--pinentry-mode", "loopback", "--passphrase", PASS,
         "--quick-gen-key", f"Test <{email}>", "default", "default", "never")
    return _gpg(home, "--pinentry-mode", "loopback", "--passphrase", PASS,
                "--armor", "--export-secret-keys", email).decode()


@pytest.fixture
def encrypted(tmp_path):
    """An encrypted KB plus the armored private key that opens it."""
    home = tmp_path / "gnupg"
    key = _make_key(home, "kb-owner@example.invalid")
    plain = build_kb(tmp_path / "handbook.sqlite")
    kbs = tmp_path / "kbs"
    kbs.mkdir()
    out = kbs / "handbook.sqlite.gpg"
    _gpg(home, "--trust-model", "always", "--recipient", "kb-owner@example.invalid",
         "--output", str(out), "--encrypt", str(plain))
    os.remove(plain)
    yield {"path": str(out), "dir": str(kbs), "key": key, "home": home}
    subprocess.run(["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"],
                   capture_output=True)


def test_opens_with_injected_key_and_never_writes_plaintext(encrypted):
    before = set(os.listdir(encrypted["dir"]))
    with KnowledgeBase(encrypted["path"], embedder=None, pgp_key=encrypted["key"],
                       pgp_passphrase=PASS) as kb:
        assert kb.name == "handbook" and kb.info()["encrypted"] is True
        assert kb.search("parental leave", mode="lexical").hits
    assert set(os.listdir(encrypted["dir"])) == before
    assert not glob.glob("/dev/shm/fuse-kb-gpg-*")


def test_key_and_passphrase_from_environment(encrypted, monkeypatch, tmp_path):
    key_file = tmp_path / "key.asc"
    key_file.write_text(encrypted["key"])
    monkeypatch.setenv("FUSE_KB_PGP_KEY_FILE", str(key_file))
    monkeypatch.setenv("FUSE_KB_PGP_PASSPHRASE", PASS)
    lib = KBLibrary(encrypted["dir"], embedder=None)
    assert lib.names == ["handbook"]
    assert lib.get("handbook").search("W-4", mode="lexical").hits


def test_users_own_keyring(encrypted, monkeypatch):
    monkeypatch.setenv("GNUPGHOME", str(encrypted["home"]))
    monkeypatch.setenv("FUSE_KB_PGP_PASSPHRASE", PASS)
    with KnowledgeBase(encrypted["path"], embedder=None) as kb:
        assert kb.search("vacation", mode="lexical").hits


def test_wrong_passphrase_and_wrong_key_are_explained(encrypted, tmp_path):
    with pytest.raises(FuseKBError, match="passphrase is wrong"):
        KnowledgeBase(encrypted["path"], pgp_key=encrypted["key"],
                      pgp_passphrase="nope")
    other = _make_key(tmp_path / "other", "someone-else@example.invalid")
    with pytest.raises(FuseKBError, match="isn't available here"):
        KnowledgeBase(encrypted["path"], pgp_key=other, pgp_passphrase=PASS)


def test_cli_opens_encrypted_files(encrypted, monkeypatch, tmp_path, capsys):
    key_file = tmp_path / "key.asc"
    key_file.write_text(encrypted["key"])
    monkeypatch.setenv("FUSE_KB_PGP_PASSPHRASE", PASS)
    assert main(["search", encrypted["path"], "W-4", "--mode", "lexical",
                 "--pgp-key-file", str(key_file)]) == 0
    assert "Form W-4" in capsys.readouterr().out
