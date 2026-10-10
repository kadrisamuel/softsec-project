from pathlib import Path

PDF_FOLDER = "output/de-watermarked"

for pdf in Path(PDF_FOLDER).glob("*.pdf"):
    data = pdf.read_bytes()
    end = data.rfind(b"%%EOF")
    if end == -1:
        print(f"Skipping {pdf}: no EOF marker")
        continue
    print(f"Removing EOF marker from {pdf}")
    pdf.write_bytes(data[:end + len(b"%%EOF")] + b"\n")
