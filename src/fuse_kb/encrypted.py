"""Optional support for PGP-encrypted KB files (``<name>.sqlite.gpg``).

Encrypted files are decrypted with GnuPG straight into memory: the readable
database never touches disk. Plain ``.sqlite`` files need none of this.

Where the private key comes from, in order:

1. ``pgp_key`` / ``pgp_key_file`` arguments, or the ``FUSE_KB_PGP_KEY``
   (ASCII-armored key) / ``FUSE_KB_PGP_KEY_FILE`` environment variables.
   Meant for servers and agents whose key comes from a secrets manager. The
   key is loaded into a throwaway GnuPG home in RAM (``/dev/shm`` where
   available) that is deleted right after decryption.
2. Otherwise, your own GnuPG keyring, exactly as ``gpg --decrypt`` would
   use it, including passphrase prompts through gpg-agent.

A passphrase can come from ``pgp_passphrase`` or ``FUSE_KB_PGP_PASSPHRASE``.
There is deliberately no command-line flag for it, so it can't end up in
shell history.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Optional

from .errors import FuseKBError

ENCRYPTED_SUFFIXES = (".sqlite.gpg", ".sqlite.pgp", ".sqlite.asc")
_INSTALL_HINT = ("Install GnuPG: 'apt install gnupg' or 'dnf install gnupg2' on "
                 "Linux, 'brew install gnupg' on macOS, or Gpg4win on Windows.")


def is_encrypted(path: str) -> bool:
    return path.lower().endswith(ENCRYPTED_SUFFIXES)


def kb_name(filename: str) -> str:
    """``handbook.sqlite.gpg`` -> ``handbook``; ``handbook.sqlite`` -> ``handbook``."""
    lower = filename.lower()
    for suffix in (*ENCRYPTED_SUFFIXES, ".sqlite"):
        if lower.endswith(suffix):
            return filename[:-len(suffix)]
    return os.path.splitext(filename)[0]


def decrypt(path: str, *, key: Optional[str] = None,
            key_file: Optional[str] = None,
            passphrase: Optional[str] = None) -> bytes:
    """Decrypt a PGP-encrypted file and return its bytes. Nothing is written
    to disk except, for an injected key, a temporary keyring kept in RAM."""
    gpg = shutil.which("gpg") or shutil.which("gpg2")
    if gpg is None:
        raise FuseKBError(f"{os.path.basename(path)} is encrypted. {_INSTALL_HINT}")
    key = key or os.environ.get("FUSE_KB_PGP_KEY")
    key_file = key_file or os.environ.get("FUSE_KB_PGP_KEY_FILE")
    passphrase = passphrase if passphrase is not None else os.environ.get(
        "FUSE_KB_PGP_PASSPHRASE")
    if key_file and not key:
        with open(os.path.expanduser(key_file), encoding="utf-8") as f:
            key = f.read()

    if not key:
        return _run_decrypt([gpg], path, passphrase)

    shm = "/dev/shm" if os.path.isdir("/dev/shm") else None
    home = tempfile.mkdtemp(prefix="fuse-kb-gpg-", dir=shm)
    try:
        os.chmod(home, 0o700)
        base = [gpg, "--homedir", home]
        imported = subprocess.run(
            [*base, "--batch", "--quiet", "--import"], input=key.encode(),
            capture_output=True)
        if imported.returncode != 0:
            raise FuseKBError("Couldn't load the PGP key: "
                              + _gpg_error(imported.stderr))
        return _run_decrypt(base, path, passphrase)
    finally:
        gpgconf = shutil.which("gpgconf")
        if gpgconf:  # stop the agent that held the key for this temp home
            subprocess.run([gpgconf, "--homedir", home, "--kill", "gpg-agent"],
                           capture_output=True)
        shutil.rmtree(home, ignore_errors=True)


def _run_decrypt(base: list[str], path: str, passphrase: Optional[str]) -> bytes:
    cmd = [*base, "--quiet", "--decrypt"]
    stdin = None
    if passphrase is not None:
        cmd[1:1] = ["--batch", "--pinentry-mode", "loopback", "--passphrase-fd", "0"]
        stdin = passphrase.encode()
    cmd.append(path)
    result = subprocess.run(cmd, input=stdin, capture_output=True)
    if result.returncode != 0:
        raise FuseKBError(f"Couldn't decrypt {os.path.basename(path)}: "
                          + _gpg_error(result.stderr))
    return result.stdout


def _gpg_error(stderr: bytes) -> str:
    text = stderr.decode(errors="replace").strip()
    if "No secret key" in text:
        return ("this file was encrypted for a key that isn't available here. "
                "Use the private key matching the public key you gave Fuse.")
    if "Bad passphrase" in text or "bad passphrase" in text:
        return "the passphrase is wrong (FUSE_KB_PGP_PASSPHRASE)."
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "gpg failed"
