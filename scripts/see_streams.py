import pymupdf

## Change this:
path = "output/de-watermarked/Group_XX.pdf"

print(path)
with pymupdf.open(path) as doc:
    for page in doc:
        # PyMuPDF applies the PDF font's character mapping here, so encoded
        # text in a content stream becomes readable (for example, WMK2:...).
        for x0, y0, x1, y1, word, *_ in page.get_text("words", sort=True):
            print(f"{word} ({x0:.1f}, {y0:.1f}, {x1:.1f}, {y1:.1f})")

        for index, xref in enumerate(page.get_contents()):
            data = doc.xref_stream(xref)

            print(f"\nStream {index} (xref {xref})")
            print(f"Size: {len(data)} bytes")
            print(data[:1000].decode("latin-1", errors="replace"))
