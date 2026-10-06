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
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
CLIENT_SCRIPT = ROOT / "scripts/rmap_download.py"
DEFAULT_KEY_DIRECTORY = ROOT / "server/keys/Public-keys-20261003"
DEFAULT_PRIVATE_KEY = ROOT / "private.key"
DEFAULT_OUTPUT_DIRECTORY = ROOT / "output/rmap/all-groups"
GROUP_PATTERN = re.compile(r"Group_(\d{2})\.asc$")
HTTP_RESPONSE_PATTERN = re.compile(r"^(GET|POST) (\S+) -> HTTP (\d{3})$")


@dataclass
class GroupResult:
    """HTTP responses and overall result for one group."""

    number: str
    healthz_http: str = "-"
    msg1_http: str = "-"
    msg2_http: str = "-"
    success: bool = False


def log_child_output(
    logger: logging.Logger,
    group: str,
    base_url: str,
    result: GroupResult,
    stdout: str | bytes | None,
    stderr: str | bytes | None,
) -> None:
    """Log child output and collect HTTP codes emitted by the client."""
    status_fields = {
        ("GET", f"{base_url}/healthz"): "healthz_http",
        ("POST", f"{base_url}/api/rmap-initiate"): "msg1_http",
        ("POST", f"{base_url}/api/rmap-get-link"): "msg2_http",
    }
    for output in (stdout, stderr):
        if isinstance(output, bytes):
            output = output.decode("utf8", errors="replace")
        for line in (output or "").splitlines():
            if match := HTTP_RESPONSE_PATTERN.fullmatch(line):
                field = status_fields.get((match.group(1), match.group(2)))
                if field:
                    setattr(result, field, match.group(3))
            if line == "HEALTHZ SUCCESS":
                logger.info("%s: HEALTHZ SUCCESS", group)
            elif line.startswith("HEALTHZ FAILED:"):
                logger.error("%s: %s", group, line)
            else:
                logger.info("%s | %s", group, line)


def format_http_table(results: list[GroupResult]) -> str:
    """Render one plain-text HTTP response table for the batch."""
    headers = ("Group", "Healthz HTTP", "RMAP msg1 HTTP", "RMAP msg2 HTTP")
    widths = tuple(len(header) for header in headers)

    def row(values: tuple[str, str, str, str]) -> str:
        return " | ".join(value.ljust(width) for value, width in zip(values, widths)).rstrip()

    lines = [row(headers), "-+-".join("-" * width for width in widths)]
    lines.extend(
        row((result.number, result.healthz_http, result.msg1_http, result.msg2_http))
        for result in results
    )
    return "\n".join(lines)


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
) -> GroupResult:
    """Run the existing RMAP client for one group and report its result."""
    group = f"Group_{number}"
    group_result = GroupResult(number)
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
    except subprocess.TimeoutExpired as error:
        log_child_output(
            logger, group, base_url, group_result, error.stdout, error.stderr
        )
        logger.error("%s: child process exceeded its time limit", group)
        return group_result

    log_child_output(
        logger, group, base_url, group_result, result.stdout, result.stderr
    )
    if result.returncode:
        logger.error("%s: RMAP FAILED (exit code %d)", group, result.returncode)
        return group_result
    logger.info("%s: RMAP SUCCESS", group)
    group_result.success = True
    return group_result


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

    results = []
    for number in groups:
        results.append(run_group(number, args, passphrase, logger))

    successes = sum(result.success for result in results)
    failures = len(results) - successes

    logger.info(
        "Finished: %d succeeded, %d failed; details in %s",
        successes,
        failures,
        log_path,
    )
    logger.info("HTTP response summary (- means no response):\n%s", format_http_table(results))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
