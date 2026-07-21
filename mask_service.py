"""
mask_service.py — /combine-mask endpoint for the ALY frame cleanup pipeline.

Merges Google Vision OCR text boxes + a Grounded-SAM person mask into one
black-and-white inpainting mask (white = remove), dilated so the fill also
covers cutout edges and drop shadows around the overlay.

Install:
    1. Drop this file next to main.py
    2. requirements.txt: add   pillow, numpy, httpx
    3. main.py: add
           from mask_service import router as mask_router
           app.include_router(mask_router)
"""

import base64
import io
import os
from typing import List, Optional

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter()


class CombineMaskRequest(BaseModel):
    frame_url: Optional[str] = None         # public URL, or...
    frame_b64: Optional[str] = None         # ...raw base64 (used for Drive-hosted frames)
    person_mask_url: Optional[str] = None   # '' or None to skip
    text_boxes: List[List[int]] = []        # [[x1, y1, x2, y2], ...] pixel coords
    dilate_px: int = 12


@router.post("/combine-mask")
def combine_mask(req: CombineMaskRequest, x_api_key: str = Header(None)):
    if x_api_key != os.getenv("API_KEY"):
        raise HTTPException(401, "bad api key")

    try:
        if req.frame_b64:
            frame_bytes = base64.b64decode(req.frame_b64)
        elif req.frame_url:
            frame_bytes = httpx.get(req.frame_url, timeout=30, follow_redirects=True).content
        else:
            raise ValueError("provide frame_b64 or frame_url")
        frame = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
    except Exception as e:
        raise HTTPException(422, f"could not load frame: {e}")

    w, h = frame.size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)

    # ---- text boxes -> white rectangles ----
    for box in req.text_boxes:
        if len(box) == 4:
            x1, y1, x2, y2 = box
            draw.rectangle(
                [max(0, x1), max(0, y1), min(w, x2), min(h, y2)],
                fill=255,
            )

    # ---- person mask -> resize to frame, threshold, union ----
    if req.person_mask_url:
        try:
            pm_bytes = httpx.get(req.person_mask_url, timeout=30, follow_redirects=True).content
            pm = Image.open(io.BytesIO(pm_bytes)).convert("L").resize((w, h))
            arr = np.where(np.array(pm) > 127, 255, 0).astype(np.uint8)
            mask = Image.fromarray(np.maximum(np.array(mask), arr))
        except Exception:
            pass  # person mask is best-effort; text boxes alone still work

    # ---- dilate so inpainting covers cutout edges / drop shadows ----
    if req.dilate_px > 0:
        size = req.dilate_px * 2 + 1  # MaxFilter needs an odd kernel
        mask = mask.filter(ImageFilter.MaxFilter(size=size))

    arr = np.array(mask)
    coverage = round(float((arr > 0).mean()) * 100, 2)

    buf = io.BytesIO()
    mask.save(buf, format="PNG")

    return {
        "mask_b64": base64.b64encode(buf.getvalue()).decode(),
        "coverage_pct": coverage,
        "empty": coverage < 0.5,
        "width": w,
        "height": h,
    }
