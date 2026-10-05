#!/usr/bin/env python3
"""CLI client to request and download watermarked PDF
using RMAP from specific group's server."""

from __future__ import annotations

import sys
import argparse
import os
from pathlib import Path

import getpass
import re
import warnings

from cryptography.utils import CryptographyDeprecationWarning

warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

import pgpy
from rmap import RMAPClient, RMAPError
import requests


DEFAULT_KEY_DIRECTORY = Path("server/keys/Public-keys-20261003")
DEFAULT_OUTPUT_DIRECTORY = Path("output/rmap")
RMAP_INITIATE_PATH = "/api/rmap-initiate"
RMAP_GET_LINK_PATH = "/api/rmap-get-link"
PDF_DOWNLOAD_PATH = "/api/get-version"


def parse_args() -> argparse.Namespace:
    """Parse command-line options for the RMAP download."""
    parser = argparse.ArgumentParser(
        description="Request and download a watermarked PDF through RMAP."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Target server base URL, for example http://softsec-group-01.dsv.local.su.se:5000"
    )
    parser.add_argument(
        "--target-group",
        required=True,
        help="Target group name, for example Group_03.",
    )
    parser.add_argument(
        "--identity",
        default="Group_02"
    )
    parser.add_argument(
        "--client-private-key",
        type=Path,
        default=Path("private.key"),
    )
    parser.add_argument(
        "--server-public-key",
        type=Path,
        help="Override the public key derived from the target group.",
    )
    parser.add_argument(
        "--public-key-directory",
        type=Path,
        default=DEFAULT_KEY_DIRECTORY,
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0
    )
    parser.add_argument(
        "--verbose",
        action="store_true"
    )
    return parser.parse_args()


def resolve_server_public_key(args: argparse.Namespace) -> Path:
    """Find and validate the target group's public key."""
    if not re.fullmatch(r"Group_\d{2}", args.target_group):
        raise ValueError(
            "Target group must use the form Group_03."
        )

    public_key = (
        args.server_public_key
        or args.public_key_directory / f"{args.target_group}.asc"
    )

    if not public_key.is_file():
        raise FileNotFoundError(
            f"Server public key not found: {public_key}"
        )

    return public_key


def read_client_passphrase(private_key_path: Path) -> str | None:
    """Prompt if the client private key is password-protected."""
    if not private_key_path.is_file():
        raise FileNotFoundError(
            f"Client private key not found: {private_key_path}"
        )

    private_key, _ = pgpy.PGPKey.from_file(str(private_key_path))

    if not private_key.is_protected:
        return None

    passphrase = os.environ.get("RMAP_SERVER_PRIVATE_KEY_PASS")
    if passphrase is not None:
        return passphrase

    return getpass.getpass(
        f"Passphrase for {private_key_path}: "
    )


def post_rmap_message(
    session: requests.Session,
    url: str,
    payload: dict,
    timeout: float,
) -> dict:
    """POST an RMAP message and return its JSON response."""
    print(f"POST {url}", flush=True)
    response = session.post(
        url,
        json=payload,
        timeout=timeout,
        allow_redirects=False,
    )
    print(f"POST {url} -> HTTP {response.status_code}", flush=True)
    if 300 <= response.status_code < 400:
        raise RuntimeError("The RMAP endpoint returned a redirect.")
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected response from {url}")

    if isinstance(data.get("payload"), str):
        summary = f"encrypted payload ({len(data['payload'])} characters; omitted)"
    else:
        summary = f"JSON {data!r}"
    print(f"Response from {url}: {summary}", flush=True)

    return data


def request_download_link(
    args: argparse.Namespace,
    server_public_key: Path,
    passphrase: str | None,
) -> str:
    """Complete RMAP handshake and return the verified link token."""
    client = RMAPClient(
        identity=args.identity,
        client_private_key_path=args.client_private_key,
        server_public_key_path=server_public_key,
        passphrase=passphrase,
        verbose=args.verbose,
    )

    base_url = args.url.rstrip("/")

    with requests.Session() as session:
        response1 = post_rmap_message(
            session,
            base_url + RMAP_INITIATE_PATH,
            client.build_msg1(),
            args.timeout,
        )
        client.process_resp1(response1)

        response2 = post_rmap_message(
            session,
            base_url + RMAP_GET_LINK_PATH,
            client.build_msg2(),
            args.timeout,
        )
        returned_link = client.process_resp2(response2)

    expected_link = client.expected_link
    if expected_link is None:
        raise RuntimeError("RMAP client did not calculate an expected link.")

    if (
        returned_link != expected_link
        and not returned_link.endswith(expected_link)
    ):
        raise RuntimeError("Server returned an unexpected RMAP link.")

    if not re.fullmatch(r"[0-9a-fA-F]{32}", expected_link):
        raise RuntimeError("RMAP link is not a 32-character hexadecimal value.")

    return expected_link


MAX_PDF_BYTES = 100 * 1024 * 1024  # 100 MiB


def download_pdf(args: argparse.Namespace, link: str) -> Path:
    """Download and save the PDF under its RMAP link without replacing an existing download."""
    url = f"{args.url.rstrip('/')}{PDF_DOWNLOAD_PATH}/{link}"
    destination = args.output_directory / f"{link}.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)

    print(f"GET {url}", flush=True)
    with requests.get(
        url,
        stream=True,
        timeout=args.timeout,
        allow_redirects=False,
    ) as response:
        print(f"GET {url} -> HTTP {response.status_code}", flush=True)
        if 300 <= response.status_code < 400:
            raise RuntimeError("The PDF endpoint returned a redirect.")
        response.raise_for_status()

        created = False
        try:
            with destination.open("xb") as pdf:
                created = True
                size = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    if size == 0 and not chunk.startswith(b"%PDF-"):
                        raise RuntimeError("The response is not a PDF.")

                    size += len(chunk)
                    if size > MAX_PDF_BYTES:
                        raise RuntimeError("The PDF exceeds the 100 MiB limit.")
                    pdf.write(chunk)

                if size == 0:
                    raise RuntimeError("The server returned an empty PDF.")
        except Exception:
            if created:
                destination.unlink(missing_ok=True)
            raise

    return destination


def main() -> int:
    """Run the handshake, download and report the saved PDF path."""
    args = parse_args()

    try:
        server_public_key = resolve_server_public_key(args)
        passphrase = read_client_passphrase(args.client_private_key)
        link = request_download_link(
            args,
            server_public_key,
            passphrase
        )
        saved_pdf = download_pdf(args, link)
    except (RMAPError, requests.RequestException, OSError, ValueError, RuntimeError) as exc:
        print(f"RMAP download failed: {exc}", file=sys.stderr)
        return 1

    print(f"Saved PDF: {saved_pdf.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
