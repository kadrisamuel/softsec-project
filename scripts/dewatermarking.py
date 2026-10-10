from pathlib import Path

PDF_FOLDER = "output/de-watermarked"

def remove_eof(pdf: Path) -> bool:
    data = pdf.read_bytes()
    end = data.rfind(b"%%EOF")
    if end == -1:
        print(f"Skipping {pdf}: no EOF marker")
        return False
    print(f"Removing EOF marker from {pdf}")
    pdf.write_bytes(data[:end + len(b"%%EOF")] + b"\n")
    return True


for pdf in Path(PDF_FOLDER).glob("*.pdf"):
    remove_eof(pdf)
