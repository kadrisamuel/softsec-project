"""Remove all streams, except the selected one, from a PDF"""
from pathlib import Path

import pymupdf

## Set a specific stream and save the file, effectively removing all other streams
path = Path("output/de-watermarked/Group_XX.pdf")
output_path = path.with_name(f"{path.stem}_destreamed{path.suffix}")

with pymupdf.open(path) as doc:
    page = doc[0]
    parts = page.get_contents()

    page.set_contents(parts[1])  # original page content to leave in based on see_streams.py results
    doc.save(output_path,
             garbage=4, deflate=True)
