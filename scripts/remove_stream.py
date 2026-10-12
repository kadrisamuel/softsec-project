import pymupdf
## Set a specific stream and save the file, effectively removing all other streams
# path = "output/de-watermarked/Group_16.pdf"
path = "output/de-watermarked/Group_12.pdf"

with pymupdf.open(path) as doc:
    page = doc[0]
    parts = page.get_contents()

    page.set_contents(parts[1])  # original page content to leave in based on see_streams.py results
    doc.save("output/de-watermarked/Group_12_destreamed.pdf",
             garbage=4, deflate=True)
