"""Realistic talking-avatar frames: one base portrait + small aligned patches (mouth shapes, blink).

  uv run python scripts/avatar/build.py jobs   <base.png> <regions.json>   -> masks + jobs.json for generate.mjs
  uv run python scripts/avatar/build.py export <base.png> <regions.json>   -> app/static/avatar/{base.webp,patches,manifest.json}
  uv run python scripts/avatar/build.py check                               -> VERDICT: PASS / NOT YET
  uv run python scripts/avatar/build.py sheet                               -> avatar_build/sheet_patches.png

The image model redraws the whole picture even with a mask, so only the region is kept:
the patch alpha is the region ellipse, eroded and feathered so it lives entirely inside the region.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "avatar_build"
OUT = ROOT / "app" / "static" / "avatar"
MODEL = "gpt-image-2.5-sunburst"

KEEP = ("Keep EVERYTHING else exactly identical to the input photo: same man, same face, same skin, same lighting, "
        "same head position, same eyes and eyebrows, same hair, same shirt, same background. Photorealistic photograph.")
PATCHES = {
    "talk.half": ("mouth", "Edit only his mouth: he is mid-sentence, lips slightly parted with a small natural gap showing a hint of the upper teeth."),
    "talk.aa":   ("mouth", "Edit only his mouth and jaw: he is saying 'ah', mouth open naturally, jaw lowered a little, upper teeth visible, dark inside of the mouth."),
    "talk.ee":   ("mouth", "Edit only his mouth: he is saying 'ee', lips stretched wider into a natural speaking shape, teeth close together and visible."),
    "talk.oh":   ("mouth", "Edit only his mouth: he is saying 'oh', lips relaxed and rounded into a medium oval opening."),
    "talk.ou":   ("mouth", "Edit only his mouth: he is saying 'oo', lips pushed slightly forward into a small rounded opening."),
    "blink":     ("eyes",  "Edit only his eyes: both eyes gently closed in a natural blink, relaxed upper eyelids with eyelashes along the lid line. Eyebrows unchanged."),
}
ERODE, FEATHER = 10, 6


def region_mask(size, box, *, erode=0) -> Image.Image:
    """L-mode mask, 255 inside the region ellipse (optionally shrunk by `erode` px)."""
    m = Image.new("L", size, 0)
    x0, y0, x1, y1 = box
    ImageDraw.Draw(m).ellipse((x0 + erode, y0 + erode, x1 - erode, y1 - erode), fill=255)
    return m


def patch_alpha(size, box) -> Image.Image:
    """Feathered alpha that never leaves the region: blur of the eroded ellipse, clipped by the region."""
    soft = np.asarray(region_mask(size, box, erode=ERODE).filter(ImageFilter.GaussianBlur(FEATHER)), dtype=np.float32)
    hard = np.asarray(region_mask(size, box), dtype=np.float32) / 255
    return Image.fromarray((soft * hard).round().astype(np.uint8), "L")


def colour_match(raw: Image.Image, base: Image.Image, box) -> Image.Image:
    """Shift the redraw's colour so it matches the base in the ring where the blend happens."""
    r = np.asarray(raw.convert("RGB"), dtype=np.float32)
    b = np.asarray(base.convert("RGB"), dtype=np.float32)
    ring = np.asarray(region_mask(base.size, box), dtype=bool) & ~np.asarray(region_mask(base.size, box, erode=ERODE + FEATHER), dtype=bool)
    offset = (b[ring] - r[ring]).mean(axis=0)
    return Image.fromarray(np.clip(r + offset, 0, 255).round().astype(np.uint8), "RGB")


def cmd_jobs(base: Path, regions: dict):
    im = Image.open(base).convert("RGBA")
    masks = BUILD / "masks"
    masks.mkdir(parents=True, exist_ok=True)
    base_png = BUILD / "base_selected.png"
    im.save(base_png)
    jobs = []
    for name, (region, instruction) in PATCHES.items():
        mpath = masks / f"{region}.png"
        if not mpath.exists():
            # OpenAI edit masks: transparent where the model may paint
            mask = Image.new("RGBA", im.size, (0, 0, 0, 255))
            hole = region_mask(im.size, regions[region])
            mask.putalpha(Image.eval(hole, lambda v: 255 - v))
            mask.save(mpath)
        jobs.append({"out": str((BUILD / "raw" / f"{name}.png").relative_to(ROOT)).replace("\\", "/"),
                     "input": str(base_png.relative_to(ROOT)).replace("\\", "/"),
                     "mask": str(mpath.relative_to(ROOT)).replace("\\", "/"),
                     "prompt": f"{instruction} {KEEP}", "model": MODEL, "size": f"{im.width}x{im.height}", "quality": "high", "n": 2})
    (BUILD / "patch_jobs.json").write_text(json.dumps({"log": "avatar_build/api-log.jsonl", "jobs": jobs}, indent=1))
    print(f"wrote {len(jobs)} jobs -> avatar_build/patch_jobs.json")


def cmd_export(base: Path, regions: dict, picks: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "patches").mkdir(exist_ok=True)
    b = Image.open(base).convert("RGB")
    b.save(OUT / "base.webp", quality=90)
    manifest = {"width": b.width, "height": b.height, "regions": regions, "patches": {}}
    for name, (region, _) in PATCHES.items():
        pick = picks.get(name, 0)
        raw = BUILD / "raw" / f"{name}_{pick}.png"
        if not raw.exists():
            print(f"missing {raw.name}, skipped")
            continue
        r = Image.open(raw).convert("RGB")
        if r.size != b.size:
            r = r.resize(b.size, Image.LANCZOS)
        a = patch_alpha(b.size, regions[region])
        x0, y0, x1, y1 = regions[region]
        rgba = colour_match(r, b, regions[region])
        rgba.putalpha(a)
        crop = rgba.crop((x0, y0, x1, y1))
        crop.save(OUT / "patches" / f"{name}.png")
        manifest["patches"][name] = {"src": f"patches/{name}.png", "box": [x0, y0, x1, y1], "region": region, "from": raw.name}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"exported {len(manifest['patches'])} patches -> {OUT}")


def composite(base: Image.Image, patch: Image.Image, box) -> Image.Image:
    out = base.convert("RGBA").copy()
    out.alpha_composite(patch, (box[0], box[1]))
    return out.convert("RGB")


def evaluate(base: Image.Image, patch: Image.Image, box):
    """Returns (outside_max_diff, inside_mean_diff, seam_mean_diff)."""
    comp = np.asarray(composite(base, patch, box), dtype=np.int16)
    b = np.asarray(base.convert("RGB"), dtype=np.int16)
    diff = np.abs(comp - b).max(axis=2)
    region = np.asarray(region_mask(base.size, box), dtype=bool)
    inner = np.asarray(region_mask(base.size, box, erode=ERODE + 2 * FEATHER), dtype=bool)
    ring = region & ~np.asarray(region_mask(base.size, box, erode=ERODE), dtype=bool) | (
        np.asarray(region_mask(base.size, box, erode=ERODE - 2), dtype=bool) & ~np.asarray(region_mask(base.size, box, erode=ERODE + 2), dtype=bool))
    # seam: how different the raw redraw is from the base right where the feather starts
    full = np.zeros_like(b)
    full[:] = b
    pa = np.asarray(patch.convert("RGBA"), dtype=np.int16)
    x0, y0 = box[0], box[1]
    h, w = pa.shape[:2]
    sub = full[y0:y0 + h, x0:x0 + w]
    sub[:] = pa[..., :3]
    seam_ring = np.asarray(region_mask(base.size, box, erode=ERODE - 1), dtype=bool) & ~np.asarray(region_mask(base.size, box, erode=ERODE + 3), dtype=bool)
    seam = np.abs(full - b).mean(axis=2)[seam_ring].mean()
    return int(diff[~region].max() if (~region).any() else 0), float(diff[inner].mean()), float(seam)


def cmd_check():
    man = json.loads((OUT / "manifest.json").read_text())
    base = Image.open(OUT / "base.webp").convert("RGB")
    results, ok = [], True
    # prove the check can fail first
    any_name, any_p = next(iter(man["patches"].items()))
    box = any_p["box"]
    unchanged = base.crop(tuple(box)).convert("RGBA")
    unchanged.putalpha(patch_alpha(base.size, box).crop(tuple(box)))
    shifted = Image.open(OUT / any_p["src"]).convert("RGBA")
    arr = np.asarray(shifted).copy()
    arr[..., :3] = np.clip(arr[..., :3].astype(int) + 40, 0, 255)
    shifted = Image.fromarray(arr.astype(np.uint8), "RGBA")
    _, in_u, _ = evaluate(base, unchanged, box)
    _, _, seam_s = evaluate(base, shifted, box)
    can_fail = in_u < 4 and seam_s > 12
    print(f"self-test: unchanged patch inside diff {in_u:.1f} (must be <4), colour-shifted patch seam {seam_s:.1f} (must be >12) -> {'ok' if can_fail else 'BROKEN'}")
    ok &= can_fail
    for name, p in man["patches"].items():
        patch = Image.open(OUT / p["src"]).convert("RGBA")
        outside, inside, seam = evaluate(base, patch, p["box"])
        good = outside == 0 and inside >= 6 and seam <= 12
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} {name:10} outside max {outside} (must be 0) | inside mean {inside:5.1f} (>=6, it really changed) | seam {seam:5.1f} (<=12)")
    print("VERDICT:", "PASS" if ok else "NOT YET")


def cmd_sheet():
    man = json.loads((OUT / "manifest.json").read_text())
    base = Image.open(OUT / "base.webp").convert("RGB")
    frames = [("base (neutral)", base)] + [(n, composite(base, Image.open(OUT / p["src"]).convert("RGBA"), p["box"])) for n, p in man["patches"].items()]
    # full frames, then 2x crops of the face so mouths and eyes are judged at a useful size
    face = man["regions"]["face"]
    W = 300
    rows = []
    for label, f in frames:
        rows.append((label, f.resize((W, W)), f.crop(tuple(face)).resize((W, int(W * (face[3] - face[1]) / (face[2] - face[0]))))))
    ch = max(r[2].height for r in rows)
    sheet = Image.new("RGB", (len(rows) * (W + 10) + 10, W + ch + 60), "white")
    d = ImageDraw.Draw(sheet)
    for i, (label, full, crop) in enumerate(rows):
        x = 10 + i * (W + 10)
        d.text((x, 5), label, fill="black")
        sheet.paste(full, (x, 25))
        sheet.paste(crop, (x, 35 + W))
    out = BUILD / "sheet_patches.png"
    sheet.save(out)
    print("saved", out)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd in ("jobs", "export"):
        base, regions = Path(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text())
        if cmd == "jobs":
            cmd_jobs(base, regions)
        else:
            picks = json.loads(Path(sys.argv[4]).read_text()) if len(sys.argv) > 4 else {}
            cmd_export(base, regions, picks)
    elif cmd == "check":
        cmd_check()
    elif cmd == "sheet":
        cmd_sheet()
