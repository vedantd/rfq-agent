#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine
import database

test_lines = [
    (3, "1-1/2\" OD SS tube, 16 ga wall, #4 polished, 20' sticks x 12"),
    (4, "alum sheet .063 5052 4x10 qty 15"),
    (5, "1/4\" 6061 plate 4x8, need 4"),
    (6, "Galv sheet 18 ga 4x8 G90 - 30 sheets"),
]

catalog = database.load_catalog()

for line_no, raw_text in test_lines:
    print(f"\n{'='*80}")
    print(f"RFQ-01 Line {line_no}: {raw_text}")
    print('='*80)
    
    line = engine.extract_rule_line(raw_text, line_no)
    
    print(f"Extracted:")
    print(f"  material: {line.get('material')}")
    print(f"  form: {line.get('form')}")
    print(f"  grade: {line.get('grade')}")
    print(f"  thickness_in: {line.get('thickness_in')}")
    print(f"  width_in: {line.get('width_in')}")
    print(f"  length_in: {line.get('length_in')}")
    print(f"  quantity: {line.get('quantity')}")
    print(f"  finish: {line.get('finish')}")
    
    # Try to analyze
    analyzed = engine.analyze_line(line, catalog=catalog)
    
    print(f"\nAnalysis:")
    print(f"  Status: {analyzed.get('status')}")
    print(f"  Match: {analyzed.get('match', {}).get('sku') if analyzed.get('match') else 'None'}")
    print(f"  Candidates: {analyzed.get('match_candidates', [])[:3]}")
    print(f"  Blockers: {analyzed.get('blockers', [])}")
    print(f"  Clarifications: {analyzed.get('clarifications', [])}")
