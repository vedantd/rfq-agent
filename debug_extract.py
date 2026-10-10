#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine
import database

# Debug RFQ-01 Line 1
raw_text = "304 SS sheet 16ga 4x8, #4 finish w/ PVC, qty 24"
print(f"Raw: {raw_text}\n")

line = engine.extract_rule_line(raw_text, 1)

print("Extracted fields:")
for k, v in sorted(line.items()):
    if v is not None:
        print(f"  {k}: {v}")

print("\nMissing fields:")
missing = [f for f in ("material","form","grade","thickness_in","width_in","length_in","quantity") if line.get(f) is None]
for f in missing:
    print(f"  - {f}")

# Try to analyze
print("\n" + "="*80)
catalog = database.load_catalog()
print(f"Catalog has {len(catalog)} SKUs")

# Search for candidates that match what we extracted
line_material = (line.get('material') or '').replace('_', ' ')
line_form = (line.get('form') or '').replace('_', ' ')
line_grade = (line.get('grade') or '').lower()
line_finish = (line.get('finish') or '').upper().strip()

print(f"\nSearching for: material={line_material}, form={line_form}, grade={line_grade}, finish={line_finish}")
print(f"  thickness={line.get('thickness_in')}, size={line.get('width_in')}x{line.get('length_in')}")

matches = 0
for item in catalog:
    cat_material = (item.get('material_family') or '').lower().strip()
    cat_form = (item.get('form') or '').lower().strip()
    cat_grade = (item.get('grade') or '').lower().strip()
    cat_finish = (item.get('finish') or '').upper().strip()
    cat_thickness = float(item.get('thickness_in', 0)) if item.get('thickness_in') else None
    cat_width = float(item.get('width_in', 0)) if item.get('width_in') else None
    cat_length = float(item.get('length_in', 0)) if item.get('length_in') else None
    
    line_material_cmp = line_material.lower().strip()
    line_form_cmp = line_form.lower().strip()
    line_thickness = float(line.get('thickness_in')) if line.get('thickness_in') else None
    line_width = float(line.get('width_in')) if line.get('width_in') else None
    line_length = float(line.get('length_in')) if line.get('length_in') else None
    
    # Check all criteria
    if cat_material != line_material_cmp or cat_form != line_form_cmp or cat_grade != line_grade:
        continue
    if line_finish and cat_finish != line_finish:
        continue
    if line_thickness and cat_thickness:
        if abs(cat_thickness - line_thickness) > 0.003:
            continue
    if line_width and line_length and cat_width and cat_length:
        cat_dims = sorted([cat_width, cat_length])
        line_dims = sorted([line_width, line_length])
        if cat_dims != line_dims:
            continue
    
    matches += 1
    print(f"  Match: {item['sku']} - {cat_material} {cat_grade} {cat_form} {cat_finish}, "
          f"{item.get('thickness_in')}, {item.get('width_in')}x{item.get('length_in')}")

print(f"\nTotal candidates: {matches}")
