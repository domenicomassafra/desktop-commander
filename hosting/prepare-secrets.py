#!/usr/bin/env python3
"""Prepare a separate age candidate with the existing dotfiles writer and CAS proof."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import secrets
import sys


def native_writer():
    path = Path.home() / '.local/share/chezmoi/scripts/import-host-secret-catalog.py'
    spec = importlib.util.spec_from_file_location('catalog_writer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(output, source=None):
    output = Path(output).absolute()
    source = Path(source) if source else Path.home() / '.local/share/chezmoi/home/.chezmoitemplates/encrypted_private_catalog_minipc.json.age'
    if output.exists() or output.is_symlink() or output.suffix != '.age':
        raise ValueError('output must be a new .age ciphertext file')
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    writer = native_writer()
    catalog = writer.read_ciphertext_catalog(source)
    for name in ['DESKTOP_COMMANDER_API_TOKEN']:
        catalog.setdefault(name, secrets.token_urlsafe(32))
    writer.write_ciphertext(catalog, output)
    if hashlib.sha256(source.read_bytes()).hexdigest() != before:
        output.unlink()
        raise ValueError('source changed concurrently; candidate discarded')
    print('EXPECTED_SOURCE_SHA256=' + before)
    print('Encrypted candidate ready; canonical source and runtime unchanged: ' + str(output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--source')
    args = parser.parse_args()
    try:
        prepare(args.output, args.source)
    except (OSError, ValueError, RuntimeError):
        print('Credential preparation refused; inspect source coordination and native writer readiness.', file=sys.stderr)
        raise SystemExit(1)
