"""Waist-up avatar with arms and gestures, built around the existing head so face patches stay aligned.

  uv run python scripts/avatar/body.py outpaint-jobs        -> avatar_build/body/outpaint_jobs.json
  uv run python scripts/avatar/body.py outpaint-finish <i>  -> avatar_build/body/base_body.png (head pasted back exactly)
  uv run python scripts/avatar/body.py gesture-jobs         -> avatar_build/body/gesture_jobs.json
  uv run python scripts/avatar/body.py export <picks.json>  -> app/static/avatar/ (base, face patches remapped, gestures, manifest)
  uv run python scripts/avatar/body.py check                -> VERDICT: PASS / NOT YET
  uv run python scripts/avatar/body.py sheet                -> avatar_build/body/sheet_body.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import PATCHES, colour_match  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "avatar_build"
BODY = BUILD / "body"
OUT = ROOT / "app" / "static" / "avatar"
MODEL = "gpt-image-2.5-sunburst"
W, H = 1024, 1536
S, OX, OY = 0.6, 205, 40                       # head-shot base -> body canvas
HEAD = (280, 60, 744, 640)                      # head + neck ellipse, in head-shot coordinates
NECK_Y = 470                                    # gestures replace everything below this line (body canvas)
FEATHER = 10

GESTURES = {
    "explain":  "Both forearms raised in front of his stomach, hands open with palms slightly up, explaining something in a relaxed, natural way.",
    "point_up": "His right hand raised beside his chest, palm facing the camera, index finger extended straight up and the other fingers curled, making a point; the whole hand clearly visible in front of the shirt, well below his chin. Left arm relaxed at his side.",
    "present":  "His left arm extended out to the side at waist height with the forearm and open palm turned up, presenting something next to him; right arm relaxed at his side.",
    "crossed":  "Arms loosely crossed in front of his chest, relaxed and attentive, both hands partly visible resting on his upper arms.",
    "together": "Both hands brought together in front of his waist, fingertips touching, calm and attentive.",
}
KEEP = ("Keep his head, face, hair and neck exactly as they are. Same white linen button-down shirt with the sleeves "
        "rolled to the forearms, same navy trousers, same soft studio lighting. Keep the exact same framing as the input, from "
        "above his head down to mid-thigh, with the plain light grey studio backdrop reaching every edge of the frame; never add "
        "black bars, borders or empty areas. Photorealistic photograph, natural hands with five fingers each, anatomically correct arms.")


def head_xy(x, y):
    return OX + x * S, OY + y * S


def ellipse_mask(size, box, erode=0) -> Image.Image:
    m = Image.new("L", size, 0)
    x0, y0, x1, y1 = box
    ImageDraw.Draw(m).ellipse((x0 + erode, y0 + erode, x1 - erode, y1 - erode), fill=255)
    return m


def head_box_body():
    (x0, y0), (x1, y1) = head_xy(HEAD[0], HEAD[1]), head_xy(HEAD[2], HEAD[3])
    return (round(x0), round(y0), round(x1), round(y1))


def head_alpha():
    """Alpha for pasting the original head back: 255 well inside, feathered inside the ellipse edge."""
    box = head_box_body()
    soft = np.asarray(ellipse_mask((W, H), box, erode=FEATHER).filter(ImageFilter.GaussianBlur(FEATHER / 2)), np.float32)
    hard = np.asarray(ellipse_mask((W, H), box), np.float32) / 255
    return Image.fromarray((soft * hard).round().astype(np.uint8), "L")


def headshot_on_canvas(img: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (W, H), (205, 205, 203))
    small = img.convert("RGB").resize((round(img.width * S), round(img.height * S)), Image.LANCZOS)
    canvas.paste(small, (OX, OY))
    return canvas


def gesture_alpha():
    """Everything except the head: the complement of the head paste-back alpha, forced to exactly 0
    inside the face so a gesture can never tint it (the blur tail would otherwise leak a few percent)."""
    g = 255 - np.asarray(head_alpha(), np.int16)
    g[np.asarray(ellipse_mask((W, H), head_box_body(), erode=FEATHER + 2), bool)] = 0
    return Image.fromarray(g.clip(0, 255).astype(np.uint8), "L")


def cmd_outpaint_jobs():
    BODY.mkdir(parents=True, exist_ok=True)
    head = Image.open(BUILD / "base_shipped.png")
    canvas = headshot_on_canvas(head)
    canvas.save(BODY / "canvas.png")
    mask = Image.new("RGBA", (W, H), (0, 0, 0, 0))              # transparent = model may paint
    mask.putalpha(ellipse_mask((W, H), head_box_body(), erode=6))  # opaque = keep the head
    mask.save(BODY / "outpaint_mask.png")
    prompt = ("Extend this photograph into a waist-up portrait of the same man standing and facing the camera. "
              "Show his shoulders, both arms and both hands, relaxed naturally at his sides, and his torso down to the waist. "
              + KEEP + " Plain light grey studio backdrop filling the whole frame.")
    jobs = [{"out": "avatar_build/body/raw/base.png", "input": "avatar_build/body/canvas.png", "mask": "avatar_build/body/outpaint_mask.png",
             "prompt": prompt, "model": MODEL, "size": f"{W}x{H}", "quality": "high", "n": 3}]
    (BODY / "outpaint_jobs.json").write_text(json.dumps({"log": "avatar_build/api-log.jsonl", "jobs": jobs}, indent=1))
    print("wrote avatar_build/body/outpaint_jobs.json")


def cmd_outpaint_finish(i: int):
    raw = Image.open(BODY / "raw" / f"base_{i}.png").convert("RGB").resize((W, H))
    head = headshot_on_canvas(Image.open(BUILD / "base_shipped.png"))
    out = raw.copy()
    out.paste(head, (0, 0), head_alpha())
    out.save(BODY / "base_body.png")
    print("saved avatar_build/body/base_body.png")


def cmd_gesture_jobs():
    mask = Image.new("RGBA", (W, H), (0, 0, 0, 0))                # transparent = model may paint
    mask.putalpha(ellipse_mask((W, H), head_box_body(), erode=6))   # opaque = keep the head
    mask.save(BODY / "gesture_mask.png")
    jobs = [{"out": f"avatar_build/body/raw/g_{name}.png", "input": "avatar_build/body/base_body.png", "mask": "avatar_build/body/gesture_mask.png",
             "prompt": f"Change only his arm pose: {desc} {KEEP}",
             "model": MODEL, "size": f"{W}x{H}", "quality": "high", "n": 2} for name, desc in GESTURES.items()]
    (BODY / "gesture_jobs.json").write_text(json.dumps({"log": "avatar_build/api-log.jsonl", "jobs": jobs}, indent=1))
    print(f"wrote {len(jobs)} gesture jobs")


def cmd_export(picks: dict):
    base = Image.open(BODY / "base_body.png").convert("RGB")
    head_man = json.loads((BUILD / "headshot_manifest.json").read_text())
    for d in ("patches", "gestures"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    base.save(OUT / "base.webp", quality=90)
    shipped = Image.open(OUT / "base.webp").convert("RGB")      # build against the exact shipped pixels
    man = {"width": W, "height": H, "view": [0, 0, W, H], "patches": {}, "gestures": {}}
    # face patches: the head-shot patches, scaled and moved onto the body canvas
    for name, p in head_man["patches"].items():
        patch = Image.open(BUILD / "headshot_patches" / f"{name}.png").convert("RGBA")
        x0, y0, x1, y1 = p["box"]
        (bx0, by0), (bx1, by1) = head_xy(x0, y0), head_xy(x1, y1)
        box = [round(bx0), round(by0), round(bx1), round(by1)]
        patch.resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS).save(OUT / "patches" / f"{name}.png")
        man["patches"][name] = {"src": f"patches/{name}.png", "box": box, "region": p["region"]}
    ga = gesture_alpha()
    top = 0
    for name in GESTURES:
        raw = BODY / "raw" / f"g_{name}_{picks.get(name, 0)}.png"
        if not raw.exists():
            continue
        r = Image.open(raw).convert("RGB").resize((W, H))
        r = colour_match(r, shipped, head_box_body())
        rgba = r.copy()
        rgba.putalpha(ga)
        rgba.crop((0, top, W, H)).save(OUT / "gestures" / f"{name}.webp", quality=88, method=6)
        man["gestures"][name] = {"src": f"gestures/{name}.webp", "box": [0, top, W, H], "from": raw.name}
    (OUT / "manifest.json").write_text(json.dumps(man, indent=1))
    print(f"exported {len(man['patches'])} face patches, {len(man['gestures'])} gestures")


def _match_strip(raw, base, box):
    r = np.asarray(raw, np.float32)
    b = np.asarray(base, np.float32)
    x0, y0, x1, y1 = box
    off = (b[y0:y1, x0:x1] - r[y0:y1, x0:x1]).reshape(-1, 3).mean(axis=0)
    return Image.fromarray(np.clip(r + off, 0, 255).round().astype(np.uint8), "RGB")


def _composite(base, layer, box):
    out = base.convert("RGBA").copy()
    out.alpha_composite(layer, (box[0], box[1]))
    return out.convert("RGB")


def cmd_check():
    man = json.loads((OUT / "manifest.json").read_text())
    base = Image.open(OUT / "base.webp").convert("RGB")
    b = np.asarray(base, np.int16)
    hb = head_box_body()
    inner = np.asarray(ellipse_mask((W, H), hb, erode=FEATHER + 2), bool)          # must be untouched
    outside = ~np.asarray(ellipse_mask((W, H), hb), bool)                           # the body
    ring = np.asarray(ellipse_mask((W, H), hb), bool) & ~inner                       # where the blend happens
    def measure(layer, box):
        comp = np.asarray(_composite(base, layer, box), np.int16)
        d = np.abs(comp - b)
        return int(d.max(axis=2)[inner].max()), float(d.max(axis=2)[outside].mean()), float(d.mean(axis=2)[ring].mean())
    ok = True
    # self-test: the base itself as a layer = no change; a black layer over everything must hit the face
    same = base.convert("RGBA"); same.putalpha(gesture_alpha())
    black = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    _, unchanged, _ = measure(same, [0, 0])
    face_hit, _, _ = measure(black, [0, 0])
    can_fail = unchanged < 1 and face_hit > 50
    print(f"self-test: unchanged layer body change {unchanged:.1f} (<1); full black layer face diff {face_hit} (>50) -> {'ok' if can_fail else 'BROKEN'}")
    ok &= can_fail
    for name, g in man["gestures"].items():
        face, body, seam = measure(Image.open(OUT / g["src"]).convert("RGBA"), g["box"])
        good = face == 0 and body >= 6 and seam <= 14
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} gesture {name:9} face max diff {face} (must be 0) | body change {body:5.1f} (>=6) | head-edge seam {seam:5.1f} (<=14)")
    for name, p in man["patches"].items():
        layer = Image.open(OUT / p["src"]).convert("RGBA")
        comp = np.asarray(_composite(base, layer, p["box"]), np.int16)
        d = np.abs(comp - b).max(axis=2)
        x0, y0, x1, y1 = p["box"]
        out = d.copy(); out[y0:y1, x0:x1] = 0
        inside = float(d[y0:y1, x0:x1].mean())
        good = int(out.max()) == 0 and inside >= 2
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} face   {name:9} outside max {int(out.max())} (must be 0) | inside change {inside:5.1f} (>=2)")
    print("VERDICT:", "PASS" if ok else "NOT YET")


def cmd_sheet():
    man = json.loads((OUT / "manifest.json").read_text())
    base = Image.open(OUT / "base.webp").convert("RGB")
    frames = [("base (relaxed)", base)]
    for name, g in man["gestures"].items():
        frames.append((name, _composite(base, Image.open(OUT / g["src"]).convert("RGBA"), g["box"])))
    p = man["patches"]["talk.aa"]
    frames.append(("base + talk.aa", _composite(base, Image.open(OUT / p["src"]).convert("RGBA"), p["box"])))
    w = 300
    h = int(w * H / W)
    sheet = Image.new("RGB", (len(frames) * (w + 10) + 10, h + 40), "white")
    d = ImageDraw.Draw(sheet)
    for i, (label, f) in enumerate(frames):
        x = 10 + i * (w + 10)
        d.text((x, 6), label, fill="black")
        sheet.paste(f.resize((w, h)), (x, 30))
    sheet.save(BODY / "sheet_body.png")
    print("saved avatar_build/body/sheet_body.png")


if __name__ == "__main__":
    c = sys.argv[1]
    if c == "outpaint-jobs":
        cmd_outpaint_jobs()
    elif c == "outpaint-finish":
        cmd_outpaint_finish(int(sys.argv[2]))
    elif c == "gesture-jobs":
        cmd_gesture_jobs()
    elif c == "export":
        cmd_export(json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 else {})
    elif c == "check":
        cmd_check()
    elif c == "sheet":
        cmd_sheet()
