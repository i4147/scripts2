#!/usr/bin/env python3
"""Encrypt and decrypt files with AES-256-GCM or GPG.

AES mode uses a versioned chunked format. Each chunk is independently
authenticated, and a final authenticated record detects truncated files.
"""


import argparse
import getpass
import os
import secrets
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO, Sequence

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"FENCRYPT"
VERSION = 1
SALT_SIZE = 16
NONCE_PREFIX_SIZE = 8
KEY_SIZE = 32
TAG_SIZE = 16
DEFAULT_CHUNK_SIZE = 1024 * 1024
MAX_CHUNK_SIZE = 16 * 1024 * 1024
# Header: magic, version, salt, nonce prefix, chunk size.
HEADER = struct.Struct(">8sB16s8sI")
UINT32 = struct.Struct(">I")
FINAL_COUNTER = 0xFFFFFFFF


class FileEncryptorError(Exception):
    """An expected input, format, or cryptographic error."""


def read_exact(stream: BinaryIO, size: int) -> bytes:
    """Read exactly size bytes, raising if the input ends early."""
    data = stream.read(size)
    if len(data) != size:
        raise FileEncryptorError("Input file is truncated or malformed.")
    return data


def derive_password_key(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit key from a password using scrypt."""
    if not password:
        raise FileEncryptorError("Password must not be empty.")

    kdf = Scrypt(
        salt=salt,
        length=KEY_SIZE,
        n=2**15,
        r=8,
        p=1,
    )
    return kdf.derive(password.encode("utf-8"))


def load_key_file(path: Path) -> bytes:
    """Load a raw 32-byte AES key."""
    try:
        key = path.read_bytes()
    except OSError as exc:
        raise FileEncryptorError(f"Cannot read key file: {exc}") from exc

    if len(key) != KEY_SIZE:
        raise FileEncryptorError(f"Key file must contain exactly {KEY_SIZE} raw bytes.")
    return key


def get_encryption_key(
    *,
    salt: bytes,
    key_file: Path | None,
    password_env: str | None,
    confirm_password: bool,
) -> bytes:
    """Get an encryption key from a key file or a prompted/environment password."""
    if key_file is not None:
        if password_env is not None:
            raise FileEncryptorError("--key-file and --password-env cannot be used together.")
        return load_key_file(key_file)

    if password_env is not None:
        password = os.environ.get(password_env)
        if password is None:
            raise FileEncryptorError(f"Environment variable {password_env!r} is not set.")
    else:
        password = getpass.getpass("Password: ")
        if confirm_password:
            confirmation = getpass.getpass("Confirm password: ")
            if password != confirmation:
                raise FileEncryptorError("Passwords do not match.")

    return derive_password_key(password, salt)


def get_decryption_key(
    *,
    salt: bytes,
    key_file: Path | None,
    password_env: str | None,
) -> bytes:
    """Get a decryption key from a key file or a prompted/environment password."""
    return get_encryption_key(
        salt=salt,
        key_file=key_file,
        password_env=password_env,
        confirm_password=False,
    )


def make_nonce(prefix: bytes, counter: int) -> bytes:
    """Build a 96-bit GCM nonce from an 8-byte prefix and 32-bit counter."""
    return prefix + UINT32.pack(counter)


def make_aad(header: bytes, counter: int, plaintext_size: int) -> bytes:
    """Bind each encrypted record to its header, counter, and plaintext size."""
    return header + UINT32.pack(counter) + UINT32.pack(plaintext_size)


def encrypt_stream(
    source: BinaryIO,
    destination: BinaryIO,
    *,
    key: bytes,
    chunk_size: int,
) -> None:
    """Encrypt a stream into the file-encryptor chunked format."""
    salt = secrets.token_bytes(SALT_SIZE)
    nonce_prefix = secrets.token_bytes(NONCE_PREFIX_SIZE)
    header = HEADER.pack(MAGIC, VERSION, salt, nonce_prefix, chunk_size)

    destination.write(header)
    cipher = AESGCM(key)
    counter = 0

    while True:
        chunk = source.read(chunk_size)
        if not chunk:
            break

        # Reserve the final counter value for the authenticated end marker.
        if counter >= FINAL_COUNTER:
            raise FileEncryptorError("Input is too large for this file format.")

        aad = make_aad(header, counter, len(chunk))
        ciphertext = cipher.encrypt(make_nonce(nonce_prefix, counter), chunk, aad)
        destination.write(UINT32.pack(len(chunk)))
        destination.write(ciphertext)
        counter += 1

    # An authenticated zero-length record marks a complete file and detects
    # truncation, including for empty input files.
    final_aad = make_aad(header, counter, 0)
    final_tag = cipher.encrypt(
        make_nonce(nonce_prefix, counter),
        b"",
        final_aad,
    )
    destination.write(UINT32.pack(0))
    destination.write(final_tag)


def decrypt_stream(source: BinaryIO, destination: BinaryIO, *, key: bytes) -> None:
    """Decrypt and authenticate a file-encryptor stream."""
    header = read_exact(source, HEADER.size)
    magic, version, salt, nonce_prefix, chunk_size = HEADER.unpack(header)

    if magic != MAGIC:
        raise FileEncryptorError("Not a file-encryptor file.")
    if version != VERSION:
        raise FileEncryptorError(f"Unsupported file format version: {version}.")
    if not 1 <= chunk_size <= MAX_CHUNK_SIZE:
        raise FileEncryptorError("Invalid or unsupported chunk size.")

    cipher = AESGCM(key)
    counter = 0

    while True:
        length_bytes = read_exact(source, UINT32.size)
        plaintext_size = UINT32.unpack(length_bytes)[0]

        if plaintext_size == 0:
            if counter > FINAL_COUNTER:
                raise FileEncryptorError("Invalid record counter.")
            tag = read_exact(source, TAG_SIZE)
            aad = make_aad(header, counter, 0)
            try:
                cipher.decrypt(make_nonce(nonce_prefix, counter), tag, aad)
            except InvalidTag as exc:
                raise FileEncryptorError("Authentication failed: wrong password/key or damaged file.") from exc

            if source.read(1):
                raise FileEncryptorError("Unexpected data after the final record.")
            return

        if plaintext_size > chunk_size:
            raise FileEncryptorError("Invalid record size.")
        if counter >= FINAL_COUNTER:
            raise FileEncryptorError("Invalid record counter.")

        ciphertext = read_exact(source, plaintext_size + TAG_SIZE)
        aad = make_aad(header, counter, plaintext_size)
        try:
            plaintext = cipher.decrypt(
                make_nonce(nonce_prefix, counter),
                ciphertext,
                aad,
            )
        except InvalidTag as exc:
            raise FileEncryptorError("Authentication failed: wrong password/key or damaged file.") from exc

        destination.write(plaintext)
        counter += 1


def default_output_path(input_path: Path, *, decrypt: bool) -> Path:
    """Choose a conventional output filename."""
    if decrypt:
        if input_path.suffix == ".fenc":
            return input_path.with_suffix("")
        return input_path.with_name(input_path.name + ".decrypted")
    return input_path.with_name(input_path.name + ".fenc")


def ensure_distinct_paths(input_path: Path, output_path: Path) -> None:
    """Disallow in-place operations to avoid platform-specific data loss."""
    try:
        source_resolved = input_path.resolve(strict=True)
        output_resolved = output_path.resolve(strict=False)
    except OSError as exc:
        raise FileEncryptorError(f"Cannot resolve input/output path: {exc}") from exc

    if source_resolved == output_resolved:
        raise FileEncryptorError("Input and output paths must be different.")


def write_atomically(
    input_path: Path,
    output_path: Path,
    *,
    force: bool,
    operation: str,
) -> None:
    """Write output to a private temporary file, then atomically replace target."""
    if not input_path.is_file():
        raise FileEncryptorError(f"Input is not a regular file: {input_path}")
    ensure_distinct_paths(input_path, output_path)

    if output_path.exists() and not force:
        raise FileEncryptorError(f"Output already exists: {output_path} (use --force to replace it).")

    parent = output_path.parent
    if not parent.is_dir():
        raise FileEncryptorError(f"Output directory does not exist: {parent}")

    temp_name: str | None = None
    try:
        with input_path.open("rb") as source:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=parent,
                prefix=f".{output_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temp_name = temporary.name
                operation(source, temporary)
                temporary.flush()
                os.fsync(temporary.fileno())

        if output_path.exists() and not force:
            raise FileEncryptorError(f"Output already exists: {output_path} (use --force to replace it).")

        os.replace(temp_name, output_path)
        temp_name = None
    except OSError as exc:
        raise FileEncryptorError(f"File operation failed: {exc}") from exc
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def run_aes_encrypt(args: argparse.Namespace) -> None:
    """Run AES-GCM encryption from parsed command-line arguments."""
    input_path: Path = args.input
    output_path: Path = args.output or default_output_path(input_path, decrypt=False)
    salt = secrets.token_bytes(SALT_SIZE)
    key = get_encryption_key(
        salt=salt,
        key_file=args.key_file,
        password_env=args.password_env,
        confirm_password=args.password_env is None and args.key_file is None,
    )

    # The salt is generated by encrypt_stream, so password-derived keys must use
    # the exact salt stored in that stream. Use this wrapper to derive it once.
    # This function is replaced below by the salt-aware operation.
    del key
    del salt

    def operation(source: BinaryIO, destination: BinaryIO) -> None:
        salt_for_file = secrets.token_bytes(SALT_SIZE)
        key_for_file = get_encryption_key(
            salt=salt_for_file,
            key_file=args.key_file,
            password_env=args.password_env,
            confirm_password=args.password_env is None and args.key_file is None,
        )
        # Build the stream with the same salt used for key derivation.
        encrypt_stream_with_salt(
            source,
            destination,
            key=key_for_file,
            salt=salt_for_file,
            chunk_size=args.chunk_size,
        )

    write_atomically(input_path, output_path, force=args.force, operation=operation)
    print(f"Encrypted: {output_path}")


def encrypt_stream_with_salt(
    source: BinaryIO,
    destination: BinaryIO,
    *,
    key: bytes,
    salt: bytes,
    chunk_size: int,
) -> None:
    """Encrypt a stream using a caller-provided salt for password derivation."""
    nonce_prefix = secrets.token_bytes(NONCE_PREFIX_SIZE)
    header = HEADER.pack(MAGIC, VERSION, salt, nonce_prefix, chunk_size)
    destination.write(header)

    cipher = AESGCM(key)
    counter = 0
    while True:
        chunk = source.read(chunk_size)
        if not chunk:
            break
        if counter >= FINAL_COUNTER:
            raise FileEncryptorError("Input is too large for this file format.")

        ciphertext = cipher.encrypt(
            make_nonce(nonce_prefix, counter),
            chunk,
            make_aad(header, counter, len(chunk)),
        )
        destination.write(UINT32.pack(len(chunk)))
        destination.write(ciphertext)
        counter += 1

    final_tag = cipher.encrypt(
        make_nonce(nonce_prefix, counter),
        b"",
        make_aad(header, counter, 0),
    )
    destination.write(UINT32.pack(0))
    destination.write(final_tag)


def run_aes_decrypt(args: argparse.Namespace) -> None:
    """Run AES-GCM decryption from parsed command-line arguments."""
    input_path: Path = args.input
    output_path: Path = args.output or default_output_path(input_path, decrypt=True)

    def operation(source: BinaryIO, destination: BinaryIO) -> None:
        header = read_exact(source, HEADER.size)
        magic, version, salt, _nonce_prefix, chunk_size = HEADER.unpack(header)
        if magic != MAGIC:
            raise FileEncryptorError("Not a file-encryptor file.")
        if version != VERSION:
            raise FileEncryptorError(f"Unsupported file format version: {version}.")
        if not 1 <= chunk_size <= MAX_CHUNK_SIZE:
            raise FileEncryptorError("Invalid or unsupported chunk size.")

        key = get_decryption_key(
            salt=salt,
            key_file=args.key_file,
            password_env=args.password_env,
        )
        # decrypt_stream expects the header to be at the current stream position.
        # Reconstruct a reader containing the already-read header.
        import io

        combined_source = io.BytesIO(header + source.read())
        decrypt_stream(combined_source, destination, key=key)

    write_atomically(input_path, output_path, force=args.force, operation=operation)
    print(f"Decrypted: {output_path}")


def generate_key(path: Path, *, force: bool) -> None:
    """Create a raw 32-byte key file with restrictive permissions."""
    if path.exists() and not force:
        raise FileEncryptorError(f"Key file already exists: {path} (use --force to replace it).")
    if not path.parent.is_dir():
        raise FileEncryptorError(f"Directory does not exist: {path.parent}")

    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temp_name = temporary.name
            os.chmod(temp_name, 0o600)
            temporary.write(secrets.token_bytes(KEY_SIZE))
            temporary.flush()
            os.fsync(temporary.fileno())

        if path.exists() and not force:
            raise FileEncryptorError(f"Key file already exists: {path} (use --force to replace it).")
        os.replace(temp_name, path)
        temp_name = None
    except OSError as exc:
        raise FileEncryptorError(f"Could not create key file: {exc}") from exc
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass

    print(f"Created 32-byte key file: {path}")
    print("Keep this key secure; anyone who has it can decrypt your files.")


def run_gpg(args: argparse.Namespace, *, decrypt: bool) -> None:
    """Run GPG using its configured agent/keyring without exposing passphrases."""
    input_path: Path = args.input
    output_path: Path = args.output or default_output_path(input_path, decrypt=decrypt)

    if not input_path.is_file():
        raise FileEncryptorError(f"Input is not a regular file: {input_path}")
    ensure_distinct_paths(input_path, output_path)
    if output_path.exists() and not args.force:
        raise FileEncryptorError(f"Output already exists: {output_path} (use --force to replace it).")
    if not output_path.parent.is_dir():
        raise FileEncryptorError(f"Output directory does not exist: {output_path.parent}")

    if decrypt:
        command = [
            "gpg",
            "--batch",
            "--yes",
            "--output",
            "-",
            "--decrypt",
            str(input_path),
        ]
    else:
        if not args.recipient:
            raise FileEncryptorError("GPG encryption requires --recipient.")
        command = [
            "gpg",
            "--batch",
            "--yes",
            "--output",
            "-",
            "--encrypt",
            "--recipient",
            args.recipient,
            str(input_path),
        ]

    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temp_name = temporary.name
            result = subprocess.run(
                command,
                stdout=temporary,
                stderr=subprocess.PIPE,
                check=False,
            )
            temporary.flush()
            os.fsync(temporary.fileno())

        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise FileEncryptorError(f"GPG failed{': ' + detail if detail else '.'}")

        if output_path.exists() and not args.force:
            raise FileEncryptorError(f"Output already exists: {output_path} (use --force to replace it).")
        os.replace(temp_name, output_path)
        temp_name = None
    except FileNotFoundError as exc:
        raise FileEncryptorError("GPG was not found. Install GnuPG and ensure 'gpg' is on PATH.") from exc
    except OSError as exc:
        raise FileEncryptorError(f"GPG file operation failed: {exc}") from exc
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass

    print(f"{'Decrypted' if decrypt else 'Encrypted'} with GPG: {output_path}")


def add_common_file_options(parser: argparse.ArgumentParser) -> None:
    """Add options shared by file-processing commands."""
    parser.add_argument("input", type=Path, help="input file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output path (default: add/remove .fenc)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output file",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(
        prog="file-encryptor",
        description="Encrypt/decrypt files with AES-256-GCM or GPG.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    encrypt_parser = subparsers.add_parser("encrypt", help="encrypt with AES-256-GCM")
    add_common_file_options(encrypt_parser)
    encrypt_parser.add_argument(
        "--key-file",
        type=Path,
        help="raw 32-byte key file instead of a password",
    )
    encrypt_parser.add_argument(
        "--password-env",
        metavar="NAME",
        help="read password from environment variable NAME (less safe than prompting)",
    )
    encrypt_parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"chunk size in bytes, 1..{MAX_CHUNK_SIZE} (default: {DEFAULT_CHUNK_SIZE})",
    )
    encrypt_parser.set_defaults(handler=run_aes_encrypt)

    decrypt_parser = subparsers.add_parser("decrypt", help="decrypt AES-GCM files")
    add_common_file_options(decrypt_parser)
    decrypt_parser.add_argument(
        "--key-file",
        type=Path,
        help="raw 32-byte key file instead of a password",
    )
    decrypt_parser.add_argument(
        "--password-env",
        metavar="NAME",
        help="read password from environment variable NAME (less safe than prompting)",
    )
    decrypt_parser.set_defaults(handler=run_aes_decrypt)

    gpg_encrypt_parser = subparsers.add_parser(
        "gpg-encrypt",
        help="encrypt to a GPG recipient (requires GnuPG)",
    )
    add_common_file_options(gpg_encrypt_parser)
    gpg_encrypt_parser.add_argument(
        "--recipient",
        help="GPG recipient identifier, email, or key fingerprint",
    )
    gpg_encrypt_parser.set_defaults(handler=lambda args: run_gpg(args, decrypt=False))

    gpg_decrypt_parser = subparsers.add_parser(
        "gpg-decrypt",
        help="decrypt a GPG file (requires GnuPG)",
    )
    add_common_file_options(gpg_decrypt_parser)
    gpg_decrypt_parser.set_defaults(handler=lambda args: run_gpg(args, decrypt=True))

    key_parser = subparsers.add_parser("generate-key", help="generate a 32-byte key")
    key_parser.add_argument("output", type=Path, help="path for the new key file")
    key_parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing key file",
    )
    key_parser.set_defaults(handler=lambda args: generate_key(args.output, force=args.force))

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run the selected command."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "encrypt" and not 1 <= args.chunk_size <= MAX_CHUNK_SIZE:
        parser.error(f"--chunk-size must be between 1 and {MAX_CHUNK_SIZE}")

    try:
        args.handler(args)
    except (FileEncryptorError, OSError) as exc:
        print(f"file-encryptor: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
