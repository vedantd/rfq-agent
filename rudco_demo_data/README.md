# RudCo RFQ-to-Quote: demo dataset

Synthetic data for the Get Hired Hack "RFQ to Quote" track. **Every supplier, mill, price and market index here is invented.** Label it that way in the demo.

## 1. Domain decision

**Architectural metals**: stainless, aluminum, galvanized and carbon-steel sheet, plate, tube and shapes, as used in hospitality and residential fit-outs (desk cladding, elevator cabs, handrails, trim, stairs).

Why this domain:
- Items are clean attribute combinations (grade × form × thickness × size × finish), so there is a single correct spec a judge can check.
- The mess is real. Gauge means different thicknesses per material, units mix feet, inches and mm, and the same item gets written five ways.
- Compliance is concrete: MTRs, country of origin and melt, Buy America, AAMA 611, LEED recycled content.
- It matches the sponsor's own examples ("304 SS sheet 16ga 4x8").

## 2. Files

| Path | What it is |
|---|---|
| `rudco_demo.db` | SQLite with every table below. This is the fake database. |
| `catalog/catalog.csv` / `.json` | 99 SKUs from the fictional supplier *Gowanus Metal Supply* |
| `catalog/synonyms.csv` | Buyer shorthand → canonical term (SS, galv, #4, 4x8, L, HSS, MTR…) |
| `catalog/gauge_table.csv` | Gauge → inches for stainless, galvanized, carbon steel and aluminum |
| `catalog/tube_wall_gauge.csv` | Tube wall gauge (16 ga tube = 0.065, not 0.060) |
| `catalog/compliance_rules.csv` | 10 simplified demo rules: trigger → catalog field → pass condition → action |
| `benchmarks/price_benchmarks.csv` | 20 $/lb ranges (low / median / high) per grade, form and finish |
| `benchmarks/market_index.csv` | 6 months of nickel, aluminum, HRC and alloy surcharge (all synthetic) |
| `rfqs/rfq_01_hotel_lobby_email.eml` | Casual email, private job, 8 lines |
| `rfqs/rfq_02_transit_buy_america_email.eml` | Terse forwarded email, Buy America applies, 8 lines |
| `rfqs/rfq_03_residential_gc_form.pdf` | Formal GC RFQ form, metric sizes, LEED, AAMA 611, 8 lines |
| `rfqs/rfq_04_fabricator_bom.xlsx` | Messy BOM: title rows, blank rows, "TBD" qty, old rev tab, 8 lines |
| `rfqs/answer_key.csv` | Expected result for all 32 lines; use it as your eval set |
| `tools/generate.py` | Regenerates everything deterministically |

## 3. Catalog schema (key fields)

`sku` · `description` · `material_family` · `grade` · `temper` · `form` · `shape` · `finish` · `standard` · `dual_cert` · `gauge` · `thickness_in` · `width_in` · `height_in` · `length_in` · `uom` · `weight_lb_each` · `price_per_lb` · `unit_price` · `unit_price_qty10` (−5%) · `unit_price_qty50` (−9%) · `benchmark_id` · `country_of_origin` · `country_of_melt` · `mill` · `mtr_available` · `mtr_type` · `buy_america_compliant` · `dfars_compliant` · `certifications` · `recycled_content_pct` · `stock_qty` · `lead_time_days` · `notes`

Dimension conventions: sheet/plate use thickness × width × length. Round tube uses `width_in` = OD and `thickness_in` = wall. Angles and tubes use width × height × wall. All lengths are in inches.

`benchmark_id` links every SKU to its market range. That link is how the agent explains why a price is competitive.

## 4. Answer key statuses

| Status | Meaning | Count |
|---|---|---|
| `MATCH` | One clear spec; one or more eligible SKUs | 15 |
| `MATCH_ASSUMPTION` | Matched with a low-risk, logged assumption (temper, metric conversion, 1/8" = 11 ga, ft → lengths) | 8 |
| `CLARIFY` | Missing info that changes price or product; ask the buyer | 6 |
| `NO_MATCH` | Not stocked; say so, never substitute silently | 3 |

`compliance_result` is separate: `OK`, `WARN` or `BLOCK`.

## 5. Traps worth showing in the demo

- **RFQ-01 L8**: "use your best judgment." The agent must still ask.
- **RFQ-01 L2**: no finish given. Don't copy #4 from line 1.
- **RFQ-01 L3**: 16 ga *tube* wall is 0.065, not sheet 0.060.
- **RFQ-02 L6**: the TW sheet is ~8% cheaper but fails Buy America, so pick the US SKU.
- **RFQ-02 L7**: origin says US, but **melt is MX**. Block it.
- **RFQ-02 L1**: 316L is covered by dual cert, but origin is KR and stock is 0, so it's a double flag.
- **RFQ-03 L1**: metric (1.5 mm, 1220×2440) maps to 16 ga 48×96; log the conversion.
- **RFQ-03 L5**: 304 flat bar exists, but the spec forbids substitution. Ask, don't swap.
- **RFQ-04 L2**: 0.0598 is the carbon-steel 16 ga decimal, and the line is a likely duplicate of L1.
- **RFQ-04 L6**: 300 ft becomes 15 × 20 ft lengths.
- **RFQ-04 L8**: our price is **above** the benchmark high. The agent should say so honestly.
- **RFQ-04 L3**: tread plate has no MTR, so WARN.

## 6. Still open

The brief requires "NicrronNinoo and Block Convey". Confirm what these are and where they plug in before building the pipeline.
