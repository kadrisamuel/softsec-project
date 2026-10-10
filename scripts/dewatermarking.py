from pathlib import Path
import re

PDF_FOLDER = Path("output/de-watermarked")
NEW_ID = "0123456789ABCDEF0123456789ABCDEF"

pattern = re.compile(
    rb"(/ID\s*\[\s*<)[0-9A-Fa-f]{32}(>\s*<)"
    rb"[0-9A-Fa-f]{32}(>\s*\])"
)

def remove_eof(pdf: Path, data: bytes, eof: int) -> bool:
    data = pdf.read_bytes()
    end = data.rfind(b"%%EOF")
    if end == -1:
        print(f"Skipping {pdf}: no EOF marker")
        return False
    print(f"Removing EOF marker from {pdf}")
    pdf.write_bytes(data[:end + len(b"%%EOF")] + b"\n")
    return True


def set_id(pdf: Path, data: bytes, eof: int, trailer_start: int) -> bool:
    if trailer_start < 0 or eof < trailer_start:
        print(f"No final text trailer found: {pdf}")
        return False

    trailer = data[trailer_start:eof]
    if b"/Encrypt" in trailer or b"/ByteRange" in data:
        print(f"Encrypted or signed PDF; aborting mission: {pdf}")
        return False

    matches = list(pattern.finditer(trailer))
    if len(matches) != 1:
        print(f"Expected one ID pair in final trailer: {pdf}")
        return False

    match = matches[0]
    replacement = (
        match.group(1) + NEW_ID.encode("ascii")
        + match.group(2) + NEW_ID.encode("ascii")
        + match.group(3)
    )
    updated = data[:trailer_start] + pattern.sub(
        replacement, trailer, count=1
    ) + data[eof:]

    pdf.write_bytes(updated)
    print(f"Updated ID for {pdf}")
    return True


for pdf in PDF_FOLDER.glob("*.pdf"):
    data = pdf.read_bytes()
    eof = data.rfind(b"%%EOF")
    trailer_start = data.rfind(b"trailer")

    remove_eof(pdf, data, eof)
    set_id(pdf, data, eof, trailer_start)
