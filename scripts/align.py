"""
1. Render both PDFs at the same resolution.
2. Estimate rotation, shift, and scale with OpenCV.
3. Warp the altered image once into the reference page’s dimensions,
    then check alignment by overlaying the two images.
4. Package into a PDF to run watermark extraction as usual
"""

from pathlib import Path

import pymupdf
import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
GROUP_KEYS_FILE = PROJECT_ROOT / "output/attribution/group_key.txt"

def render_first_page(pdf_path: Path, png_path: Path) -> None:
    """Render PDF page to PNG at 2048 pixel width"""
    with pymupdf.open(pdf_path) as document:
        page = document[0]
        scale = 2048 / page.rect.width
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
        png_path.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(png_path)

# render_first_page(
#     Path("/softsec-project/Group_02.pdf"),
#     Path("output/attribution/original.png"),
# )


from PIL import Image

original = Image.open("output/attribution/original.png").convert("L")
altered = Image.open("output/attribution/altered.png").convert("L")

height = min(original.height, altered.height)
original = original.crop((0, 0, 2048, height))
altered = altered.crop((0, 0, 2048, height))

assert original.size == altered.size

# from PIL import ImageChops, ImageOps

# difference = ImageChops.difference(original, altered)
# ImageOps.autocontrast(difference).save("output/attribution/difference.png")

## Reduce size for easier computation
original_small = cv2.resize(np.asarray(original), None, fx=0.25, fy=0.25)
altered_small = cv2.resize(np.asarray(altered), None, fx=0.25, fy=0.25)

print(original_small.shape, altered_small.shape)

warp = np.eye(2, 3, dtype=np.float32)
criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)

score, warp = cv2.findTransformECC(
    original_small.astype(np.float32) / 255,
    altered_small.astype(np.float32) / 255,
    warp,
    cv2.MOTION_AFFINE,
    criteria,
)
print("alignment score:", score)
print("warp:", warp)
# alignment score: 0.9954403007729845
# warp: [[ 0.99861544  0.01323262 -4.440112  ]
#  [-0.01281075  0.99892765  3.5981724 ]]


## umwarp the full-size altered image in grayscale for checking
full_warp = warp.copy()
full_warp[:, 2] *= 4

aligned = cv2.warpAffine(
    np.asarray(altered),
    full_warp,
    original.size,
    flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
    borderValue=255,
)
Image.fromarray(aligned).save("output/attribution/aligned.png")

## umwarp the full-size altered image in RGB
altered_rgb = Image.open("output/attribution/altered.png").convert("RGB")
aligned_rgb = cv2.warpAffine(
    np.asarray(altered_rgb),
    full_warp,
    original.size,
    flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
    borderValue=(255, 255, 255),
)
Image.fromarray(aligned_rgb).save("output/attribution/aligned_rgb.png")

## Put the aligned altered RGB image into a PDF
with pymupdf.open("Group_02.pdf") as source:
    page_size = source[0].rect

with pymupdf.open() as document:
    page = document.new_page(width=page_size.width, height=page_size.height)
    pixmap = pymupdf.Pixmap(
        pymupdf.csRGB, aligned_rgb.shape[1], aligned_rgb.shape[0],
        aligned_rgb.tobytes(), False,
    )
    page.insert_image(page.rect, stream=pixmap.tobytes("png"))
    document.save("output/attribution/aligned.pdf")
