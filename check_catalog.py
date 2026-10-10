#!/usr/bin/env python
import sqlite3

conn = sqlite3.connect('rudco_demo_data/rudco_demo.db')
cursor = conn.cursor()

# Get first row from catalog to see actual column names and values
cursor.execute("SELECT * FROM catalog LIMIT 1")
row = cursor.fetchone()
columns = [description[0] for description in cursor.description]

print("Catalog table columns and first row values:")
for i, (col, val) in enumerate(zip(columns, row)):
    print(f"  {col}: {val}")

# Show row as JSON-like dict
print("\nAs dict:")
import json
row_dict = dict(zip(columns, row))
print(json.dumps(row_dict, indent=2))

conn.close()
