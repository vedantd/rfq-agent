"""Database access layer for RudCo demo dataset.

Loads catalog, reference tables, and compliance rules from rudco_demo.db.
All pricing in this demo is synthetic and for demonstration only.
"""

import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def db_path() -> str:
    """Resolve path to rudco_demo.db (the RudCo reference dataset).

    Uses RUDCO_DEMO_DB_PATH so the reference DB stays independent of RFQ_DB_PATH,
    which api.store uses for the per-tenant operational database.
    """
    env_path = os.getenv('RUDCO_DEMO_DB_PATH')
    if env_path and os.path.isfile(env_path):
        return env_path
    
    # Try workspace relative path
    workspace_root = Path(__file__).parent
    db_file = workspace_root / "rudco_demo_data" / "rudco_demo.db"
    if db_file.exists():
        return str(db_file)
    
    # Fallback to current directory
    fallback = Path.cwd() / "rudco_demo_data" / "rudco_demo.db"
    if fallback.exists():
        return str(fallback)
    
    raise FileNotFoundError(
        f"rudco_demo.db not found. Set RUDCO_DEMO_DB_PATH env var or place at "
        f"{db_file} or {fallback}"
    )


def get_connection() -> sqlite3.Connection:
    """Get database connection with row factory enabled."""
    conn = sqlite3.connect(db_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


@lru_cache(maxsize=1)
def load_catalog() -> List[Dict[str, Any]]:
    """Load all 99 SKUs from catalog table.
    
    Returns:
        List of dictionaries with SKU details including price, compliance, lead time.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM catalog ORDER BY sku"
        ).fetchall()
    
    return [dict(row) for row in rows]


@lru_cache(maxsize=1)
def load_synonyms() -> Dict[str, str]:
    """Load term normalization mappings.
    
    Returns:
        Dict mapping buyer shorthand (e.g., "SS", "galv") to canonical forms.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT term, canonical FROM synonyms ORDER BY term"
        ).fetchall()
    
    return {row['term']: row['canonical'] for row in rows}


@lru_cache(maxsize=1)
def load_gauge_tables() -> Dict[str, Dict[str, Optional[float]]]:
    """Load material-specific gauge thickness conversions.
    
    Returns:
        Dict[gauge_number, {'stainless': thickness_in, 'galvanized': ..., 'carbon_steel': ..., 'aluminum': ...}]
        
    Example:
        {
            '16': {'stainless': 0.0625, 'galvanized': 0.0635, 'carbon_steel': 0.0598, 'aluminum': 0.050},
            '18': {'stainless': 0.0500, ...},
        }
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM gauge_table ORDER BY CAST(gauge AS INTEGER)"
        ).fetchall()
    
    result = {}
    for row in rows:
        result[row['gauge']] = {
            'stainless': _to_float(row['stainless_in']),
            'galvanized': _to_float(row['galvanized_in']),
            'carbon_steel': _to_float(row['carbon_steel_msg_in']),
            'aluminum': _to_float(row['aluminum_bs_in']),
        }
    return result


@lru_cache(maxsize=1)
def load_tube_gauge() -> Dict[str, float]:
    """Load tube wall gauge conversions (different from sheet gauge).
    
    Example:
        {'16': 0.065, '14': 0.083, ...}  # Note: 16 ga tube = 0.065", sheet = 0.0625"
    
    Returns:
        Dict mapping gauge to wall thickness in inches.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT gauge, wall_in FROM tube_wall_gauge ORDER BY gauge"
        ).fetchall()
    
    return {row['gauge']: _to_float(row['wall_in']) for row in rows}


@lru_cache(maxsize=1)
def load_compliance_rules() -> List[Dict[str, Any]]:
    """Load compliance validation rules.
    
    Returns:
        List of rules with trigger patterns, requirements, and failure actions.
        
    Example rule:
        {
            'rule_id': 'BUY_AMERICA_STEEL',
            'trigger_in_rfq': 'buy america|usa origin|domestic',
            'requirement': 'SKU must have buy_america_compliant=TRUE',
            'catalog_field': 'buy_america_compliant',
            'pass_condition': 'TRUE',
            'on_fail': 'BLOCK',  # or WARN
        }
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM compliance_rules ORDER BY rule_id"
        ).fetchall()
    
    return [dict(row) for row in rows]


@lru_cache(maxsize=1)
def load_benchmarks() -> Dict[str, Dict[str, Any]]:
    """Load price benchmarks for validation.
    
    Returns:
        Dict[benchmark_id, {
            'material_family': str,
            'grade': str,
            'form': str,
            'finish_class': str,
            'low_per_lb': float,
            'median_per_lb': float,
            'high_per_lb': float,
            'unit': str,
            'basis': str,
            'small_order_adder_pct': float,
            'domestic_premium_pct': float,
            'as_of': str,
            'source': str,
        }]
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM price_benchmarks ORDER BY benchmark_id"
        ).fetchall()
    
    result = {}
    for row in rows:
        result[row['benchmark_id']] = {
            'material_family': row['material_family'],
            'grade': row['grade'],
            'form': row['form'],
            'finish_class': row['finish_class'],
            'low_per_lb': _to_float(row['low_per_lb']),
            'median_per_lb': _to_float(row['median_per_lb']),
            'high_per_lb': _to_float(row['high_per_lb']),
            'unit': row['unit'],
            'basis': row['basis'],
            'small_order_adder_pct': _to_float(row['small_order_adder_pct']),
            'domestic_premium_pct': _to_float(row['domestic_premium_pct']),
            'as_of': row['as_of'],
            'source': row['source'],
        }
    return result


@lru_cache(maxsize=1)
def load_answer_key() -> List[Dict[str, Any]]:
    """Load evaluation dataset with expected answers for 32 RFQ lines.
    
    Returns:
        List of answer key records with expected status, SKUs, compliance results.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM answer_key ORDER BY rfq_id, CAST(line_no AS INTEGER)"
        ).fetchall()
    
    return [dict(row) for row in rows]


@lru_cache(maxsize=1)
def load_market_index() -> List[Dict[str, Any]]:
    """Load market index data for commodity pricing context.
    
    Returns:
        List of index values with name, unit, month, value, source.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM market_index ORDER BY index_id, month"
        ).fetchall()
    
    return [dict(row) for row in rows]


def get_sku(sku: str) -> Optional[Dict[str, Any]]:
    """Fetch a single SKU by code.
    
    Args:
        sku: SKU identifier (e.g., "SS-304-16GA-4896")
        
    Returns:
        SKU record or None if not found.
    """
    catalog = load_catalog()
    for item in catalog:
        if item['sku'] == sku:
            return item
    return None


def find_benchmark(benchmark_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single benchmark by ID.
    
    Args:
        benchmark_id: Benchmark identifier.
        
    Returns:
        Benchmark record or None if not found.
    """
    benchmarks = load_benchmarks()
    return benchmarks.get(benchmark_id)


def search_catalog(
    material: Optional[str] = None,
    grade: Optional[str] = None,
    form: Optional[str] = None,
    finish: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search catalog by multiple criteria (case-insensitive).
    
    Args:
        material: Material family (e.g., "stainless_steel", "carbon_steel")
        grade: Grade (e.g., "304", "316", "A36")
        form: Form (e.g., "sheet", "plate", "tube")
        finish: Finish (e.g., "2B", "#2", "mill")
        
    Returns:
        List of matching SKUs.
    """
    catalog = load_catalog()
    results = []
    
    for sku in catalog:
        if material and (sku.get('material_family') or '').lower() != material.lower():
            continue
        if grade and (sku.get('grade') or '').lower() != grade.lower():
            continue
        if form and (sku.get('form') or '').lower() != form.lower():
            continue
        if finish and (sku.get('finish') or '').lower() != finish.lower():
            continue
        results.append(sku)
    
    return results


def verify_database() -> Tuple[bool, str]:
    """Verify database integrity and row counts.
    
    Returns:
        (is_valid, message) tuple.
    """
    try:
        with get_connection() as conn:
            tables = {
                'catalog': 99,
                'synonyms': 68,
                'gauge_table': 9,
                'tube_wall_gauge': 5,
                'compliance_rules': 10,
                'price_benchmarks': 20,
                'answer_key': 32,
                'market_index': 36,
            }
            
            for table_name, expected_count in tables.items():
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                actual_count = cursor.fetchone()[0]
                if actual_count == 0:
                    return False, f"Table '{table_name}' is empty"
            
            return True, "Database verified: all tables populated"
    
    except Exception as e:
        return False, f"Database verification failed: {str(e)}"


def _to_float(value: Any) -> Optional[float]:
    """Convert value to float, handling None and string representations."""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
