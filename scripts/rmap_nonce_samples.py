#!/usr/bin/env python3
"""Collect RMAP nonces from completed handshakes and inspect simple patterns.

Run only against your own deployment. Collection creates one watermarked
version per successful handshake. The output contains bearer-link components,
so it is created with owner-only file permissions.
"""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pgpy
import requests
from rmap import RMAPClient, RMAPError


MAX_U64 = (1 << 64) - 1
OUTPUT_DIRECTORY = Path(__file__).resolve().parents[1] / "output" / "rmap"
HEX_NONCE = re.compile(r"[0-9a-fA-F]{16}\Z")


@dataclass(frozen=True)
class Sample:
    """One completed handshake and the interval when its challenge was made."""

    client_nonce: int
    server_nonce: int
    started_at: datetime
    challenge_at: datetime


def positive_int(value: str) -> int:
    """Parse the requested number of handshakes."""
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("count must be at least 1")
    return number


def nonnegative_float(value: str) -> float:
    """Parse a nonnegative delay between handshakes."""
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("delay must be a finite nonnegative number")
    return number


def parse_args() -> argparse.Namespace:
    """Select collection or offline analysis."""
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    collect_parser = subcommands.add_parser(
        "collect", help="Complete handshakes and save nonces"
    )
    collect_parser.add_argument("--url", required=True, help="Your own deployment's base URL")
    collect_parser.add_argument("--server-public-key", required=True, type=Path)
    collect_parser.add_argument("--client-private-key", required=True, type=Path)
    collect_parser.add_argument("--identity", default="Group_02")
    collect_parser.add_argument("--count", required=True, type=positive_int)
    collect_parser.add_argument("--output", type=Path, help="New JSONL file; never overwritten")
    collect_parser.add_argument("--timeout", type=float, default=120.0)
    collect_parser.add_argument("--delay", type=nonnegative_float, default=0.0)

    analyze_parser = subcommands.add_parser("analyze", help="Inspect saved nonces offline")
    analyze_parser.add_argument("input", type=Path, help="JSONL file made by collect")
    return parser.parse_args()


def post_rmap(session: requests.Session, url: str, payload: dict, timeout: float) -> dict:
    """Send one protocol message and require an encrypted JSON response."""
    response = session.post(
        url, json=payload, timeout=timeout, allow_redirects=False
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"{url} returned HTTP {response.status_code}: {response.text[:250]}"
        )
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("payload"), str):
        raise RuntimeError(f"{url} returned no encrypted RMAP payload")
    return body


def complete_handshake(args: argparse.Namespace, passphrase: str | None) -> dict:
    """Use the registered private key and record when the server issued a nonce."""
    client = RMAPClient(
        identity=args.identity,
        client_private_key_path=args.client_private_key,
        server_public_key_path=args.server_public_key,
        passphrase=passphrase,
    )
    base_url = args.url.rstrip("/")
    with requests.Session() as session:
        msg1 = client.build_msg1()
        started_at = datetime.now(timezone.utc)
        response1 = post_rmap(
            session, base_url + "/api/rmap-initiate", msg1, args.timeout
        )
        challenge_at = datetime.now(timezone.utc)
        client.process_resp1(response1)

        response2 = post_rmap(
            session,
            base_url + "/api/rmap-get-link",
            client.build_msg2(),
            args.timeout,
        )
        returned_link = client.process_resp2(response2)

    expected_link = client.expected_link
    if not isinstance(expected_link, str) or not re.fullmatch(
        r"[0-9a-fA-F]{32}", expected_link
    ):
        raise RuntimeError("The completed handshake produced no 32-hex link")
    if not isinstance(returned_link, str) or (
        returned_link != expected_link and not returned_link.endswith(expected_link)
    ):
        raise RuntimeError("The returned link did not match the completed handshake")

    client_nonce = int(expected_link[:16], 16)
    server_nonce = int(expected_link[16:], 16)
    if server_nonce != client.nonceServer:
        raise RuntimeError("The link's server nonce differs from the challenge")
    return {
        "started_at_utc": started_at.isoformat(),
        "challenge_at_utc": challenge_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "client_nonce_hex": f"{client_nonce:016x}",
        "server_nonce_hex": f"{server_nonce:016x}",
    }


def output_path(args: argparse.Namespace) -> Path:
    """Choose a fresh path by default so old evidence is not overwritten."""
    if args.output is not None:
        return args.output.expanduser().resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return OUTPUT_DIRECTORY / f"rmap_nonces_{timestamp}.jsonl"


def collect(args: argparse.Namespace) -> int:
    """Complete exactly the requested number of successful handshakes."""
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("timeout must be a finite positive number")
    for key_path in (args.server_public_key, args.client_private_key):
        if not key_path.is_file():
            raise FileNotFoundError(f"Key not found: {key_path}")

    private_key, _ = pgpy.PGPKey.from_file(str(args.client_private_key))
    passphrase = None
    if private_key.is_protected:
        passphrase = getpass.getpass("Client private-key passphrase: ")

    destination = output_path(args)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    print(f"Writing completed handshakes to {destination}")
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        for index in range(1, args.count + 1):
            record = complete_handshake(args, passphrase)
            record["index"] = index
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            print(
                f"{index}/{args.count}: server nonce 0x{record['server_nonce_hex']}"
            )
            if index < args.count and args.delay:
                time.sleep(args.delay)

    print(f"Saved {args.count} completed handshakes to {destination}")
    return 0


def load_samples(path: Path) -> list[Sample]:
    """Read and validate the saved handshake records."""
    samples = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                client_hex = record["client_nonce_hex"]
                server_hex = record["server_nonce_hex"]
                if not HEX_NONCE.fullmatch(client_hex) or not HEX_NONCE.fullmatch(
                    server_hex
                ):
                    raise ValueError("nonces must have exactly 16 hex digits")
                started_at = datetime.fromisoformat(record["started_at_utc"])
                challenge_at = datetime.fromisoformat(record["challenge_at_utc"])
                if started_at.tzinfo is None or challenge_at.tzinfo is None:
                    raise ValueError("timestamps must include a timezone")
                if challenge_at < started_at:
                    raise ValueError("challenge time precedes start time")
                samples.append(
                    Sample(
                        client_nonce=int(client_hex, 16),
                        server_nonce=int(server_hex, 16),
                        started_at=started_at,
                        challenge_at=challenge_at,
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid record at line {line_number}: {exc}") from exc
    if not samples:
        raise ValueError("No completed handshakes found")
    return samples


def time_matches(samples: list[Sample], scale: int) -> int:
    """Count nonces equal to a Unix clock value during their challenge interval."""
    return sum(
        math.floor(sample.started_at.timestamp() * scale)
        <= sample.server_nonce
        <= math.ceil(sample.challenge_at.timestamp() * scale)
        for sample in samples
    )


def analyze(path: Path) -> int:
    """Report falsifiable simple patterns, without claiming a randomness proof."""
    samples = load_samples(path)
    nonces = [sample.server_nonce for sample in samples]
    count = len(nonces)
    duplicate_count = count - len(set(nonces))
    differences = [(right - left) & MAX_U64 for left, right in zip(nonces, nonces[1:])]
    varying_mask = 0
    for nonce in nonces[1:]:
        varying_mask |= nonce ^ nonces[0]

    print(f"Completed handshakes: {count}")
    print(f"Repeated server nonce values: {duplicate_count}")
    if count >= 2:
        print(f"Fixed bit positions in this sample: {64 - varying_mask.bit_count()}/64")
    print(f"All server nonces fit in 32 bits: {all(n < 1 << 32 for n in nonces)}")
    print(
        "Server nonce equals client nonce: "
        f"{sum(s.server_nonce == s.client_nonce for s in samples)}/{count}"
    )

    if count >= 3 and len(set(differences)) == 1:
        step = differences[0]
        print(f"Fixed step across this sample: 0x{step:016x}")
        print(f"Next value if the step continues: 0x{(nonces[-1] + step) & MAX_U64:016x}")
    elif count >= 3:
        adjacent = sum(step in (1, MAX_U64) for step in differences)
        print(f"Adjacent values (+1 or -1): {adjacent}/{len(differences)}")
        print("No single step fits every observed transition.")
    else:
        print("At least three samples are needed to assess a fixed step.")

    xor_values = {sample.client_nonce ^ sample.server_nonce for sample in samples}
    if count >= 3 and len(xor_values) == 1:
        print(f"Fixed client/server XOR in this sample: 0x{next(iter(xor_values)):016x}")
    offsets = {
        (sample.server_nonce - sample.client_nonce) & MAX_U64
        for sample in samples
    }
    if count >= 3 and len(offsets) == 1:
        print(f"Fixed client/server offset in this sample: 0x{next(iter(offsets)):016x}")
    for label, scale in (("seconds", 1), ("milliseconds", 1000), ("microseconds", 1000000)):
        matches = time_matches(samples, scale)
        print(f"Server nonce equals Unix {label} during challenge: {matches}/{count}")

    print("These checks only test the displayed patterns; they do not prove unpredictability.")
    return 0


def main() -> int:
    """Run the requested mode and show a concise error on failure."""
    args = parse_args()
    try:
        if args.command == "collect":
            return collect(args)
        return analyze(args.input)
    except (
        FileExistsError,
        FileNotFoundError,
        OSError,
        ValueError,
        RuntimeError,
        RMAPError,
        requests.RequestException,
    ) as exc:
        print(f"RMAP nonce {args.command} failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
