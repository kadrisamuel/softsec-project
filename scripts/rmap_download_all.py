#!/usr/bin/env python3
"""Run the existing RMAP download client against every group server."""

# 1. Create SSH tunnel (don't forget to turn wireguard on)
# ```ssh -D 1080 -N -C softsec@softsec-group-02.dsv.local.su.se```
# 2. Run with SOCKS tunnel active
# ```ALL_PROXY=socks5h://localhost:1080 python3 scripts/rmap_download_all.py```

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
CLIENT_SCRIPT = ROOT / "scripts/rmap_download.py"
DEFAULT_KEY_DIRECTORY = ROOT / "server/keys/Public-keys-20261003"
DEFAULT_PRIVATE_KEY = ROOT / "private.key"
DEFAULT_OUTPUT_DIRECTORY = ROOT / "output/rmap/all-groups"
GROUP_PATTERN = re.compile(r"Group_(\d{2})\.asc$")


def parse_args() -> argparse.Namespace:
    """Parse command-line options for the batch run."""
    parser = argparse.ArgumentParser(
        description="Run rmap_download.py once for each configured group server."
    )
    parser.add_argument("--key-directory", type=Path, default=DEFAULT_KEY_DIRECTORY)
    parser.add_argument("--client-private-key", type=Path, default=DEFAULT_PRIVATE_KEY)
    parser.add_argument("--identity", default="Group_02")
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python interpreter used to run scripts/rmap_download.py.",
    )
    parser.add_argument(
        "--url-template",
        default="http://softsec-group-{number}.dsv.local.su.se:5000",
        help="Server URL template; {number} is replaced with the two-digit group number.",
    )
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Timeout in seconds for each HTTP request (default: 5).",
    )
    return parser.parse_args()


def read_env_value(env_path: Path, name: str) -> str:
    """Read one value from the project's .env file."""
    value = dotenv_values(env_path).get(name)
    if value:
        return value
    raise ValueError(f"{name} is missing or empty in {env_path}")


def run_group(
    number: str,
    args: argparse.Namespace,
    passphrase: str,
    logger: logging.Logger,
) -> bool:
    """Run the existing RMAP client for one group and report its result."""
    group = f"Group_{number}"
    base_url = args.url_template.format(number=number).rstrip("/")
    group_output = args.output_directory / group
    command = [
        os.fspath(args.python),
        os.fspath(CLIENT_SCRIPT),
        "--url",
        base_url,
        "--target-group",
        group,
        "--identity",
        args.identity,
        "--client-private-key",
        os.fspath(args.client_private_key.resolve()),
        "--public-key-directory",
        os.fspath(args.key_directory.resolve()),
        "--output-directory",
        os.fspath(group_output.resolve()),
        "--timeout",
        str(args.timeout),
    ]
    child_env = os.environ.copy()
    child_env["RMAP_SERVER_PRIVATE_KEY_PASS"] = passphrase

    logger.info("=== %s at %s ===", group, base_url)
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=args.timeout * 3 + 10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.error("%s: child process exceeded its time limit", group)
        return False

    for line in (result.stdout + result.stderr).splitlines():
        if line == "HEALTHZ SUCCESS":
            logger.info("%s: HEALTHZ SUCCESS", group)
        elif line.startswith("HEALTHZ FAILED:"):
            logger.error("%s: %s", group, line)
        else:
            logger.info("%s | %s", group, line)
    if result.returncode:
        logger.error("%s: RMAP FAILED (exit code %d)", group, result.returncode)
        return False
    logger.info("%s: RMAP SUCCESS", group)
    return True


def main() -> int:
    """Run the client for each group key and summarize successes and failures."""
    args = parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    log_path = args.output_directory / "rmap_download_all.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf8"),
        ],
    )
    logger = logging.getLogger("rmap-download-all")

    try:
        passphrase = read_env_value(ROOT / ".env", "RMAP_SERVER_PRIVATE_KEY_PASS")
        if not CLIENT_SCRIPT.is_file():
            raise FileNotFoundError(f"RMAP client script not found: {CLIENT_SCRIPT}")
        if not args.client_private_key.is_file():
            raise FileNotFoundError(
                f"Client private key not found: {args.client_private_key}"
            )
        if not args.key_directory.is_dir():
            raise FileNotFoundError(f"Public key directory not found: {args.key_directory}")
    except (OSError, ValueError) as error:
        logger.error("Setup failed: %s", error)
        return 2

    groups = sorted(
        match.group(1)
        for key_path in args.key_directory.glob("Group_*.asc")
        if (match := GROUP_PATTERN.fullmatch(key_path.name))
    )
    if not groups:
        logger.error("No Group_NN.asc public keys found in %s", args.key_directory)
        return 2

    successes = 0
    failures = 0
    for number in groups:
        if run_group(number, args, passphrase, logger):
            successes += 1
        else:
            failures += 1

    logger.info(
        "Finished: %d succeeded, %d failed; details in %s",
        successes,
        failures,
        log_path,
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
