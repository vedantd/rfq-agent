#!/usr/bin/env python3
"""Render noisy RFQ demo images for vision-upload testing.

Requires Pillow (pip install pillow). Not a runtime dependency of QuotePilot.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = Path(__file__).resolve().parent


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    *,
    fnt: ImageFont.ImageFont,
    fill: str,
    max_width: int,
    line_gap: int = 6,
) -> int:
    x, y = xy
    words = text.split()
    line = ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_width:
            line = trial
        else:
            if line:
                draw.text((x, y), line, font=fnt, fill=fill)
                y += int(fnt.size) + line_gap
            line = word
    if line:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += int(fnt.size) + line_gap
    return y


def rfq_01_email_screenshot() -> Path:
    img = Image.new("RGB", (980, 720), "#f0f2f5")
    draw = ImageDraw.Draw(img)
    # Browser chrome
    draw.rounded_rectangle((24, 24, 956, 696), radius=12, fill="white", outline="#d0d7e2")
    draw.rectangle((24, 24, 956, 72), fill="#e8eef6")
    draw.ellipse((44, 40, 60, 56), fill="#ff5f57")
    draw.ellipse((70, 40, 86, 56), fill="#febc2e")
    draw.ellipse((96, 40, 112, 56), fill="#28c840")
    draw.text((130, 38), "mail.acme-mfg.example — Inbox", font=font(15), fill="#4a5568")

    y = 96
    meta = [
        ("From:", "procurement@acme-mfg.example"),
        ("To:", "quotes@northstar-metals.example"),
        ("Subject:", "RFQ — lobby cladding sheets (ASAP)"),
        ("Date:", "Fri, 10 Oct 2026 09:14"),
    ]
    for label, value in meta:
        draw.text((56, y), label, font=font(14, bold=True), fill="#64748b")
        draw.text((140, y), value, font=font(14), fill="#1e293b")
        y += 28
    draw.line((56, y + 4, 924, y + 4), fill="#e2e8f0", width=1)
    y += 28

    body_font = font(16)
    paragraphs = [
        "Hi team,",
        "Please quote ASAP for the hotel lobby job. PO staging #PO-88421. Ship to 1200 Market St, Floor 3.",
        "Need 20 sheets 304 SS 16ga 4x8, mill certs required.",
        "Also 10 sheets stainless 1/8 inch.",
        "Call me at (555) 014-2290 if stock is short. Thanks — Jordan Lee, ACME Procurement",
    ]
    for para in paragraphs:
        y = draw_wrapped(draw, para, (56, y), fnt=body_font, fill="#0f172a", max_width=860)
        y += 10

    path = OUT / "rfq_01_email_screenshot.png"
    img.save(path)
    return path


def rfq_02_bom_table() -> Path:
    img = Image.new("RGB", (1100, 620), "#ffffff")
    draw = ImageDraw.Draw(img)
    draw.text((40, 28), "ACME Fabrication — BOM Export", font=font(22, bold=True), fill="#111827")
    draw.text((40, 62), "Job: Lobby cladding  ·  Rev B  ·  Need-by: 2026-11-02  ·  Notes: TBD finish", font=font(14), fill="#6b7280")

    # Table
    headers = ["Item", "Qty", "Description", "Notes"]
    col_x = [40, 120, 220, 780]
    row_y = 110
    draw.rectangle((36, row_y - 8, 1064, row_y + 36), fill="#eff6ff")
    for i, h in enumerate(headers):
        draw.text((col_x[i], row_y), h, font=font(14, bold=True), fill="#1d4ed8")
    row_y += 44
    rows = [
        ("1", "20", "304 SS sheet 16ga 48x96", "mill certs / MTR"),
        ("2", "", "(blank — ignore)", "Rev B placeholder"),
        ("3", "10", "stainless sheet 1/8 inch", "grade/size TBD"),
        ("4", "1", "delivery window confirm", "not a material line"),
    ]
    for idx, row in enumerate(rows):
        bg = "#f9fafb" if idx % 2 == 0 else "#ffffff"
        draw.rectangle((36, row_y - 6, 1064, row_y + 34), fill=bg)
        for i, cell in enumerate(row):
            draw.text((col_x[i], row_y), cell, font=font(15), fill="#111827")
        row_y += 42

    draw.text((40, row_y + 20), "Exported from ERP · Do not price header/blank/admin rows", font=font(13), fill="#9ca3af")
    path = OUT / "rfq_02_bom_table.jpg"
    img.save(path, quality=92)
    return path


def rfq_03_phone_notepad() -> Path:
    # Larger canvas with vignette to look like a phone photo of a notepad
    img = Image.new("RGB", (900, 1200), "#d9d4c8")
    draw = ImageDraw.Draw(img)
    # Desk background noise
    for i in range(0, 900, 40):
        draw.line((i, 0, i + 20, 1200), fill="#cfc9bb", width=1)

    # Notepad page
    draw.rounded_rectangle((70, 90, 830, 1100), radius=8, fill="#fffef8", outline="#b8b09f")
    # Ruled lines
    for y in range(180, 1050, 36):
        draw.line((110, y, 790, y), fill="#d7e3f4", width=1)
    draw.line((150, 140, 150, 1060), fill="#f2b8b5", width=2)  # margin

    title = font(28, bold=True)
    hand = font(22)
    small = font(18)
    draw.text((170, 120), "JOB NOTES — site walk", font=title, fill="#1f2937")
    draw.text((170, 200), "call Jim before noon", font=hand, fill="#6b7280")
    draw.text((170, 250), "job #HL-204 · 88 Canal Rd", font=small, fill="#9ca3af")
    draw.text((170, 320), "MATERIALS:", font=font(20, bold=True), fill="#111827")
    draw.text((170, 380), "15 sheets 304 stainless 16ga 4x8", font=hand, fill="#0f172a")
    draw.text((170, 460), "(don't forget parking validation)", font=small, fill="#9ca3af")
    draw.text((170, 540), "— end of list —", font=small, fill="#cbd5e1")

    # Soft vignette
    vignette = Image.new("RGBA", img.size, (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)
    for r, a in ((0, 0), (40, 25), (90, 55)):
        vdraw.rectangle((r, r, 900 - r, 1200 - r), outline=(40, 40, 40, a), width=40)
    vignette = vignette.filter(ImageFilter.GaussianBlur(18))
    img = Image.alpha_composite(img.convert("RGBA"), vignette).convert("RGB")

    path = OUT / "rfq_03_phone_notepad.png"
    img.save(path)
    return path


def rfq_04_messy_forward() -> Path:
    img = Image.new("RGB", (1000, 880), "#ffffff")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 1000, 56), fill="#111827")
    draw.text((28, 16), "Forwarded message — RFQ thread", font=font(18, bold=True), fill="#f8fafc")

    y = 80
    draw.text((36, y), "From: ops@site-gc.example", font=font(14), fill="#475569")
    y += 24
    draw.text((36, y), "Subject: Fwd: Re: metal for elevator cab", font=font(14, bold=True), fill="#0f172a")
    y += 36
    draw.text((36, y), "Can you price under $200? Need these this week.", font=font(16), fill="#1e293b")
    y += 40
    draw.text((36, y), "5 sheets 316 SS 16ga 48x96", font=font(17, bold=True), fill="#0f172a")
    y += 36
    draw.text((36, y), "2 boxes 3/4in drywall screws", font=font(16), fill="#334155")
    y += 44

    quote_bg = "#f8fafc"
    draw.rectangle((36, y, 964, y + 220), fill=quote_bg, outline="#e2e8f0")
    qy = y + 16
    quoted = [
        "> On Oct 8, buyer wrote:",
        "> Circling back — still waiting on pricing.",
        "> Also grab coffee filters for the trailer.",
        "> Unsubscribe: https://lists.example/u/9981",
        "> ACME Site GC · Confidential · Do not quote this footer",
    ]
    for line in quoted:
        draw.text((52, qy), line, font=font(14), fill="#64748b")
        qy += 28

    draw.text((36, y + 250), "— End forwarded message —", font=font(13), fill="#94a3b8")
    path = OUT / "rfq_04_messy_forward.png"
    img.save(path)
    return path


def main() -> None:
    paths = [
        rfq_01_email_screenshot(),
        rfq_02_bom_table(),
        rfq_03_phone_notepad(),
        rfq_04_messy_forward(),
    ]
    for p in paths:
        print(f"wrote {p.name} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
