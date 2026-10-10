import pymupdf
from pathlib import Path

path = "output/de-watermarked/Group_16_clean.pdf"

with pymupdf.open(path) as source, pymupdf.open() as output:
    for page in source:
        pix = page.get_pixmap(dpi=150, colorspace=pymupdf.csRGB, alpha=False)
        new_page = output.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(
            new_page.rect,
            stream=pix.tobytes("jpeg", jpg_quality=25),
            keep_proportion=False,
        )

    pdf = Path(path)
    output_path = pdf.with_name(f"{pdf.stem}_rasterized_compressed.pdf")
    output.set_metadata({})
    output.save(output_path, garbage=4, deflate=True)
