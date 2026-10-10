"""Read-path tests for the RudCo demo database access layer (database.py).

These validate that every loader returns well-formed data from rudco_demo.db,
independent of the agent's extraction/matching logic. If these fail, regenerate
the DB with: cd rudco_demo_data && python tools/generate.py
"""

import database


def test_verify_database():
    is_valid, message = database.verify_database()
    assert is_valid, message


def test_load_catalog_rows_and_keys():
    catalog = database.load_catalog()
    assert len(catalog) == 99
    required = {
        'sku', 'material_family', 'grade', 'form', 'finish',
        'thickness_in', 'width_in', 'length_in', 'unit_price',
        'benchmark_id', 'country_of_origin', 'country_of_melt',
        'mill', 'mtr_available', 'buy_america_compliant',
    }
    for item in catalog:
        assert required.issubset(item.keys())
    # Numeric fields stored as TEXT must be float-parseable when present
    for item in catalog:
        for field in ('thickness_in', 'unit_price'):
            value = item.get(field)
            if value not in (None, ''):
                float(value)


def test_load_gauge_tables():
    tables = database.load_gauge_tables()
    assert '16' in tables
    row16 = tables['16']
    assert set(row16.keys()) == {'stainless', 'galvanized', 'carbon_steel', 'aluminum'}
    assert abs(row16['stainless'] - 0.060) < 1e-6


def test_load_tube_gauge():
    tube = database.load_tube_gauge()
    assert tube.get('16') is not None
    assert abs(tube['16'] - 0.065) < 1e-6


def test_load_synonyms():
    synonyms = database.load_synonyms()
    assert isinstance(synonyms, dict)
    assert len(synonyms) > 0
    for term, canonical in synonyms.items():
        assert term and canonical


def test_load_compliance_rules():
    rules = database.load_compliance_rules()
    assert len(rules) > 0
    for rule in rules:
        assert rule.get('rule_id')
        assert 'trigger_in_rfq' in rule
        assert 'on_fail' in rule


def test_load_benchmarks():
    benchmarks = database.load_benchmarks()
    assert 'BM-SS304-SH-4' in benchmarks
    bench = benchmarks['BM-SS304-SH-4']
    assert isinstance(bench['median_per_lb'], float)
    assert bench['material_family'] == 'stainless steel'


def test_load_answer_key():
    key = database.load_answer_key()
    assert len(key) == 32
    allowed = {'MATCH', 'CLARIFY', 'NO_MATCH', 'MATCH_ASSUMPTION'}
    for record in key:
        assert record['expected_status'] in allowed
        assert record['rfq_id']
        assert record['raw_text']


def test_search_catalog_filters():
    results = database.search_catalog(material='stainless steel', grade='304', form='sheet', finish='#4')
    assert len(results) > 0
    for item in results:
        assert item['material_family'].lower() == 'stainless steel'
        assert item['grade'].lower() == '304'
        assert item['form'].lower() == 'sheet'
        assert item['finish'].lower() == '#4'


def test_search_catalog_no_filters_returns_all():
    assert len(database.search_catalog()) == len(database.load_catalog())


def test_get_sku_hit_and_miss():
    catalog = database.load_catalog()
    sample_sku = catalog[0]['sku']
    assert database.get_sku(sample_sku)['sku'] == sample_sku
    assert database.get_sku('NON-EXISTENT-SKU') is None


def test_find_benchmark_hit_and_miss():
    assert database.find_benchmark('BM-SS304-SH-4') is not None
    assert database.find_benchmark('BM-DOES-NOT-EXIST') is None
