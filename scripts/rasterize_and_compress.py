"""Rasterize and compress a PDF"""
from pathlib import Path

import pymupdf

## Change this:
path = Path("output/de-watermarked/Group_XX.pdf")
output_path = path.with_name(f"{path.stem}_rasterized_compressed{path.suffix}")

with pymupdf.open(path) as source, pymupdf.open() as output:
    for page in source:
        pix = page.get_pixmap(dpi=150, colorspace=pymupdf.csRGB, alpha=False)
        new_page = output.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(
            new_page.rect,
            stream=pix.tobytes("jpeg", jpg_quality=25),
            keep_proportion=False,
        )

    output.set_metadata({})
    output.save(output_path, garbage=4, deflate=True)
