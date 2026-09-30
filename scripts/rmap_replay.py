#!/usr/bin/env python3
"""Replay a completed RMAP handshake against the group's own deployment."""
# pylint: disable=duplicate-code

from __future__ import annotations

import sys
import argparse
from pathlib import Path

import getpass
import re

import pgpy
from rmap import RMAPClient, RMAPError
import requests


DEFAULT_KEY_DIRECTORY = Path("server/keys/Public-keys-20260914")
RMAP_INITIATE_PATH = "/api/rmap-initiate"
RMAP_GET_LINK_PATH = "/api/rmap-get-link"


def parse_args() -> argparse.Namespace:
    """Parse command-line options for the RMAP replay check."""
    parser = argparse.ArgumentParser(
        description="Replay an RMAP message against your own deployment."
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

    return getpass.getpass(
        f"Passphrase for {private_key_path}: "
    )


def post_rmap_message(
    session: requests.Session,
    url: str,
    payload: dict,
    timeout: float,
    *,
    allow_error: bool = False,
) -> requests.Response:
    """POST an RMAP message; preserve an expected replay rejection."""
    response = session.post(
        url,
        json=payload,
        timeout=timeout,
        allow_redirects=False,
    )
    sent = response.request
    body = sent.body.decode("utf-8") if isinstance(sent.body, bytes) else sent.body

    print(f"REQUEST {sent.method} {sent.url}")
    print(body)
    print(f"RESPONSE HTTP {response.status_code}")
    print(response.text)

    if 300 <= response.status_code < 400:
        raise RuntimeError("The RMAP endpoint returned a redirect.")
    if not allow_error:
        response.raise_for_status()
    return response


def do_handshake(
    args: argparse.Namespace,
    server_public_key: Path,
    passphrase: str | None,
) -> requests.Response:
    """Complete a handshake, then return the response to an identical msg2."""
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
        client.process_resp1(response1.json())

        payload = client.build_msg2()
        response2 = post_rmap_message(
            session,
            base_url + RMAP_GET_LINK_PATH,
            payload,
            args.timeout,
        )
        returned_link = client.process_resp2(response2.json())

        replay_response = post_rmap_message(
            session,
            base_url + RMAP_GET_LINK_PATH,
            payload,
            args.timeout,
            allow_error=True,
        )

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

    return replay_response




def main() -> int:
    """Run one valid handshake and report the replay response."""
    args = parse_args()

    try:
        server_public_key = resolve_server_public_key(args)
        passphrase = read_client_passphrase(args.client_private_key)
        _replay_response = do_handshake(
            args,
            server_public_key,
            passphrase
        )

    except (RMAPError, requests.RequestException, OSError, ValueError, RuntimeError) as exc:
        print(f"RMAP replay check failed: {exc}", file=sys.stderr)
        return 1

    # print(f"Replay HTTP status: {replay_response.status_code}")
    # print(f"Replay response: {replay_response.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
