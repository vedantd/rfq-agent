# RudCo Database Integration Guide

This document describes the RudCo reference database schema and how it's integrated into the RFQ agent.

## Overview

The RudCo database (`rudco_demo_data/rudco_demo.db`) is a SQLite database containing:

- **Catalog**: 99 material supply SKUs with specifications and pricing
- **Benchmarks**: Market rate benchmarks for price validation
- **Compliance Rules**: Procurement requirements and restrictions
- **Gauge Tables**: Material-specific unit conversions
- **Synonyms**: Term normalization mappings
- **Answer Key**: 32 pre-evaluated RFQ lines for testing

## Schema

### `catalog` table (99 rows)

Main product catalog with supplier inventory and pricing.

| Column | Type | Notes |
|--------|------|-------|
| `sku` | TEXT PRIMARY KEY | Unique SKU (e.g., `SS304-2B-16G-4896-US`) |
| `description` | TEXT | Human-readable product description |
| `material_family` | TEXT | Material type: "stainless steel", "galvanized steel", "carbon steel", "aluminum" |
| `grade` | TEXT | Material grade (e.g., "304", "316", "A36", "5052") |
| `temper` | TEXT | (optional) Aluminum temper code (e.g., "H14") |
| `form` | TEXT | Product form: "sheet", "plate", "tube", "angle", "hss" |
| `shape` | TEXT | (redundant with form, for compatibility) |
| `finish` | TEXT | Surface finish (e.g., "2B", "#4", "BA", "mill", "polished") |
| `standard` | TEXT | Applicable standard (e.g., "ASTM A240", "ASTM A36") |
| `dual_cert` | TEXT | Alternate certification (e.g., "304/304L") |
| `gauge` | TEXT | Gauge notation if applicable (e.g., "16", "18", "14") |
| `thickness_in` | REAL | Thickness in inches (e.g., 0.060, 0.125) |
| `width_in` | REAL | Width in inches |
| `height_in` | TEXT | (for reference only) |
| `length_in` | REAL | Length in inches |
| `uom` | TEXT | Unit of measure: "EA" (each sheet/piece), "LB", "FT" |
| `weight_lb_each` | REAL | Weight per unit in pounds |
| `price_per_lb` | REAL | Price per pound (for reference) |
| `unit_price` | REAL | Price per unit (sheet/piece) in USD |
| `unit_price_qty10` | REAL | Bulk price at qty 10 |
| `unit_price_qty50` | REAL | Bulk price at qty 50 |
| `benchmark_id` | TEXT | Foreign key to `benchmarks` table (e.g., `BM-SS304-SH-2B`) |
| `country_of_origin` | TEXT | Manufacturing country (2-letter code: "US", "TW", "KR", "CN", "MX") |
| `country_of_melt` | TEXT | Steel melt source country (if different) |
| `mill` | TEXT | Supplier/manufacturer name |
| `mtr_available` | TEXT | "Y" or "N" - Mill Test Report available |
| `mtr_type` | TEXT | MTR standard (e.g., "EN 10204 3.1", "ASTM A994") |
| `buy_america_compliant` | TEXT | "Y" or "N" - US-made compliance |
| `dfars_compliant` | TEXT | "Y" or "N" - DFARS specialty metals compliance |
| `certifications` | TEXT | Comma-separated list (e.g., "ASTM A240 / ASME SA-240") |
| `recycled_content_pct` | REAL | % recycled material (estimated) |
| `stock_qty` | INTEGER | Current inventory count (illustrative) |
| `lead_time_days` | INTEGER | Days to ship (e.g., 2, 7, 21) |
| `min_order_qty` | INTEGER | Minimum order quantity |
| `notes` | TEXT | Additional remarks |

### `benchmarks` table

Market pricing benchmarks used for quote validation.

| Column | Type | Notes |
|--------|------|-------|
| `benchmark_id` | TEXT PRIMARY KEY | Benchmark ID (e.g., `BM-SS304-SH-2B`) |
| `material` | TEXT | Material (e.g., "stainless steel") |
| `grade` | TEXT | Grade (e.g., "304") |
| `form` | TEXT | Form (e.g., "sheet") |
| `finish` | TEXT | Finish (e.g., "2B") |
| `thickness_in` | REAL | Thickness in inches |
| `median_per_lb` | REAL | Median price per pound from market sources |
| `median_per_unit` | REAL | Median price per unit (sheet/piece) |
| `basis` | TEXT | Data source (e.g., "SYNTHETIC_DEMO_BENCHMARK") |
| `as_of` | TEXT | Date of benchmark (YYYY-MM-DD) |

### `compliance_rules` table

Rules for procurement compliance (e.g., Buy America, DFARS, MTR).

| Column | Type | Notes |
|--------|------|-------|
| `rule_id` | TEXT PRIMARY KEY | Rule identifier (e.g., "BUYAMERICA-001") |
| `trigger_in_rfq` | TEXT | Keywords in RFQ that activate rule (pipe-separated, e.g., "buy america\|usa\|domestic") |
| `requirement` | TEXT | Description of requirement |
| `catalog_field` | TEXT | Catalog column to check (e.g., "country_of_origin", "mtr_available") |
| `pass_condition` | TEXT | Value that satisfies rule (e.g., "US", "Y") |
| `on_fail` | TEXT | Action if requirement not met: "BLOCK" or "WARN" |
| `guidance` | TEXT | Explanation for compliance team |

Example rows:
- **BUYAMERICA-001**: Triggers on "buy america" → checks `country_of_origin` == "US" → BLOCK if not met
- **DFARS-002**: Triggers on "dfars" → checks `country_of_melt` == "US" → BLOCK if not met
- **MTR-001**: Triggers on "mtr" or "mill cert" → checks `mtr_available` == "Y" → BLOCK if not met

### `gauge_table` table

Material-specific sheet gauge-to-thickness mappings.

| Column | Type | Notes |
|--------|------|-------|
| `gauge` | TEXT PRIMARY KEY | Gauge number (e.g., "16", "18", "14", "20", "22", "24") |
| `stainless` | REAL | Thickness in inches for stainless steel |
| `galvanized` | REAL | Thickness in inches for galvanized steel |
| `carbon_steel` | REAL | Thickness in inches for carbon steel |
| `aluminum` | REAL | Thickness in inches for aluminum |

Example:
- Gauge 16: SS=0.0625", Galv=0.0598", Carbon=0.0625", Alum=0.0500"

### `tube_wall_gauge` table

Tube wall gauge-to-thickness mappings (different from sheet gauge).

| Column | Type | Notes |
|--------|------|-------|
| `gauge` | TEXT PRIMARY KEY | Gauge number (e.g., "16", "18", "14") |
| `thickness_in` | REAL | Wall thickness in inches |

Example: Tube 16 ga = 0.065" wall (vs. sheet 16 ga = 0.0625")

### `synonyms` table

Term normalization for RFQ text preprocessing.

| Column | Type | Notes |
|--------|------|-------|
| `term` | TEXT PRIMARY KEY | Term to replace (e.g., "ss", "galv", "hdg") |
| `canonical` | TEXT | Normalized form (e.g., "stainless steel", "galvanized", "hot dip galvanized") |

Applied during `engine.normalize_synonym()`.

### `answer_key` table (32 rows)

Test data with expected agent outcomes for evaluation.

| Column | Type | Notes |
|--------|------|-------|
| `rfq_id` | TEXT | RFQ identifier (e.g., "RFQ-01") |
| `line_no` | INTEGER | Line number in RFQ |
| `raw_text` | TEXT | Original line text from RFQ |
| `expected_status` | TEXT | Expected agent status: "MATCH", "CLARIFY", "NO_MATCH", "MATCH_ASSUMPTION" |
| `expected_skus` | TEXT | Comma-separated list of acceptable SKUs |
| `compliance_result` | TEXT | Expected compliance status (e.g., "OK", "OK: ...", "BLOCK: ...") |
| `notes` | TEXT | Test case notes (e.g., trap descriptions) |

## Using the Database in Code

### Loading Data

```python
import database

# Load full catalog
catalog = database.load_catalog()  # Returns list of dicts

# Search catalog
results = database.search_catalog(material='stainless', grade='304', finish='#4')

# Load reference tables
benchmarks = database.load_benchmarks()
compliance_rules = database.load_compliance_rules()
gauge_tables = database.load_gauge_tables()
tube_gauge = database.load_tube_gauge()
synonyms = database.load_synonyms()
answer_key = database.load_answer_key()

# Verify database health
is_valid, message = database.verify_database()
```

### Integration Points

1. **engine.py - `analyze_line()`**: Uses `database.load_catalog()` to match RFQ specs to SKUs
2. **engine.py - `resolve_gauge_to_thickness()`**: Uses `database.load_gauge_tables()` and `database.load_tube_gauge()`
3. **engine.py - `normalize_synonym()`**: Uses `database.load_synonyms()` for term normalization
4. **engine.py - `apply_compliance_rules()`**: Uses `database.load_compliance_rules()` to validate candidates
5. **tests/eval_suite.py**: Uses `database.load_answer_key()` for automated testing

### API Endpoints

New catalog endpoints in `app.py`:

```bash
# Search catalog
curl http://localhost:8000/v1/catalog/search?material=stainless&grade=304 \
  -H "X-API-Key: rudco-demo-key"

# Get benchmarks
curl http://localhost:8000/v1/catalog/benchmarks \
  -H "X-API-Key: rudco-demo-key"

# Get compliance rules
curl http://localhost:8000/v1/catalog/compliance-rules \
  -H "X-API-Key: rudco-demo-key"

# Get gauge table
curl http://localhost:8000/v1/catalog/gauge-table \
  -H "X-API-Key: rudco-demo-key"

# Get tube gauge
curl http://localhost:8000/v1/catalog/tube-gauge \
  -H "X-API-Key: rudco-demo-key"

# Get synonyms
curl http://localhost:8000/v1/catalog/synonyms \
  -H "X-API-Key: rudco-demo-key"

# Verify database health
curl http://localhost:8000/v1/catalog/health \
  -H "X-API-Key: rudco-demo-key"
```

## Testing with the Evaluation Suite

Run the evaluation suite to validate the agent against known RFQ lines:

```bash
cd rfq-agent
python tests/eval_suite.py
```

This tests:
- **Database loaders** - all tables accessible and populated
- **Extraction accuracy** - parser correctly identifies material, grade, gauge, dimensions
- **Normalization** - synonyms and gauge conversion applied
- **Catalog matching** - RFQ specs matched to correct SKUs
- **Compliance checking** - procurement rules evaluated correctly
- **Pricing** - benchmark comparisons calculated

## Extending the Database

### Adding SKUs

1. Use the HTTP API: `PUT /v1/catalog/items/{sku}`
2. Or insert directly into SQLite:

```sql
INSERT INTO catalog (sku, description, material_family, grade, form, ...) VALUES (...)
```

### Adding Benchmarks

```sql
INSERT INTO benchmarks (benchmark_id, material, grade, form, finish, median_per_lb, basis, as_of)
VALUES ('BM-SS316-SH-4', 'stainless steel', '316', 'sheet', '#4', 3.45, 'DEMO', '2026-10-10')
```

### Adding Compliance Rules

```sql
INSERT INTO compliance_rules (rule_id, trigger_in_rfq, requirement, catalog_field, pass_condition, on_fail)
VALUES ('LEED-001', 'leed|recyclable', 'Must be LEED-eligible', 'recycled_content_pct', '50', 'WARN')
```

## Performance Notes

- Catalog: 99 SKUs, fully loaded on startup
- Gauge tables: ~6 materials × ~8 gauges
- Benchmarks: ~30 entries
- Compliance rules: ~15 rules
- Synonyms: ~50 terms

All data is loaded into memory on first access and cached. No hot reload; restart the server to apply database changes.

## Troubleshooting

### Database file not found

```
RuntimeError: Database verification failed: Could not connect to database
```

Check the path:
```python
import database
database.verify_database()  # Returns (False, error message)
```

Set the correct path in `.env`:
```dotenv
RUDCO_DEMO_DB_PATH=./rudco_demo_data/rudco_demo.db
```

### Empty answer key

If `database.load_answer_key()` returns 0 records:
- Verify `answer_key` table exists: `sqlite3 rudco_demo.db "SELECT COUNT(*) FROM answer_key"`
- Check schema alignment in `database.py`

### Gauge resolution returns None

If `resolve_gauge_to_thickness('16', 'stainless_steel')` returns `thickness_in: None`:
- Verify gauge tables are loaded: `database.load_gauge_tables()`
- Check if material key matches catalog (`stainless` not `stainless_steel`)
