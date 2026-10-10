import database as db

print("=== verify_database ===")
print(db.verify_database())

print("\n=== catalog: first 5 SKUs ===")
for item in db.load_catalog()[:5]:
    print(f"  {item['sku']:28} {item['material_family']:16} {item['grade']:5} {item['form']:6} "
          f"{item['finish']:14} t={item['thickness_in']:>6} {item['width_in']}x{item['length_in']} "
          f"${item['unit_price']} origin={item['country_of_origin']}")

print("\n=== search_catalog(stainless 304 sheet #4) ===")
for item in db.search_catalog(material="stainless steel", grade="304", form="sheet", finish="#4"):
    print(f"  {item['sku']:28} t={item['thickness_in']:>6} {item['width_in']}x{item['length_in']} "
          f"origin={item['country_of_origin']} ${item['unit_price']}")

print("\n=== gauge 16 ===", db.load_gauge_tables()["16"])
print("=== tube 16 ===", db.load_tube_gauge().get("16"))
print("=== benchmark BM-SS304-SH-4 ===", db.find_benchmark("BM-SS304-SH-4"))
print("=== get_sku(SS304-4-16G-4896-US) ===", db.get_sku("SS304-4-16G-4896-US") is not None)

rules = db.load_compliance_rules()
print(f"\n=== compliance rules: {len(rules)} ===", [r["rule_id"] for r in rules])

key = db.load_answer_key()
print(f"\n=== answer_key: {len(key)} records ===")
print(f"  first: {key[0]['rfq_id']} L{key[0]['line_no']} -> {key[0]['expected_status']}")
