import re
from pathlib import Path

import pymupdf

PDF_FOLDER = Path("output/de-watermarked")
NEW_ID = b"0123456789ABCDEF0123456789ABCDEF"

ID_PATTERN = re.compile(
    rb"(/ID\s*\[\s*<)[0-9A-Fa-f]{32}(>\s*<)"
    rb"[0-9A-Fa-f]{32}(>\s*\])"
)


def final_trailer(data: bytes) -> tuple[int, int]:
    eof = data.rfind(b"%%EOF")
    trailer_start = data.rfind(b"trailer", 0, eof)
    return trailer_start, eof


def set_id(data: bytes, pdf: Path) -> bytes | None:
    trailer_start, eof = final_trailer(data)
    if trailer_start < 0 or eof < trailer_start:
        print(f"No final text trailer found: {pdf}")
        return None

    trailer = data[trailer_start:eof]
    matches = list(ID_PATTERN.finditer(trailer))
    if len(matches) != 1:
        print(f"Expected one ID pair in final trailer: {pdf}")
        return None

    match = matches[0]
    replacement = match.group(1) + NEW_ID + match.group(2) + NEW_ID + match.group(3)
    updated_trailer = ID_PATTERN.sub(replacement, trailer, count=1)
    return data[:trailer_start] + updated_trailer + b"%%EOF\n"


def scrub(pdf: Path) -> bool:
    source_data = pdf.read_bytes()
    trailer_start, eof = final_trailer(source_data)
    if b"/ByteRange" in source_data or (
        trailer_start >= 0 and b"/Encrypt" in source_data[trailer_start:eof]
    ):
        print(f"Encrypted or signed PDF; skipping {pdf}")
        return False

    with pymupdf.open(pdf) as doc:
        doc.scrub(
            metadata=True,
            xml_metadata=True,
            javascript=True,
            embedded_files=True,
            attached_files=True,
            hidden_text=True,
            redactions=False,
            reset_fields=False,
            reset_responses=False,
        )
        scrubbed_data = doc.tobytes(garbage=4, deflate=True)

    updated_data = set_id(scrubbed_data, pdf)
    if updated_data is None:
        return False

    output_path = pdf.with_name(f"{pdf.stem}_scrubbed.pdf")
    output_path.write_bytes(updated_data)
    print(f"Scrubbed metadata and updated ID: {output_path}")
    return True


if __name__ == "__main__":
    for pdf in sorted(PDF_FOLDER.glob("*.pdf")):
        if "scrubbed" not in pdf.stem.split("_"):
            scrub(pdf)
