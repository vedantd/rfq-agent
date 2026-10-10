#!/usr/bin/env python
import re

raw = "304 SS sheet 16ga 4x8, #4 finish w/ PVC, qty 24"
s = raw.lower()

# Test finish detection
finish_match = re.search(r"\b(2b|#2|#4|#8|ba|mill|polished|bright|satin|raw)\b", s)
print(f"Finish match: {finish_match}")
if finish_match:
    print(f"  Group: {finish_match.group(1)}")
else:
    print("No finish match found")
    
# Check if the text contains the pattern
if "#4" in raw.lower():
    print("'#4' found in raw text")
    
# Try alternative regex
alt_match = re.search(r"(#\d|2b|ba|mill|polished|bright|satin|raw)", s)
print(f"Alt match: {alt_match}")
if alt_match:
    print(f"  Group: {alt_match.group(1)}")
