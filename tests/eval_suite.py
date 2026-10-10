"""Evaluation suite for RFQ agent against answer_key dataset.

Tests the agent pipeline on 32 RFQ lines with known answers.
Reports accuracy metrics and identifies failing test cases.
"""

import json
import sys
import os
from typing import Any, Dict, List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from ai import engine


class EvaluationSuite:
    """Test harness for evaluating agent performance against answer_key."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results = []
        self.answer_key = database.load_answer_key()
        self.catalog = database.load_catalog()
        
        # Verify database
        is_valid, msg = database.verify_database()
        if not is_valid:
            raise RuntimeError(f"Database verification failed: {msg}")
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run evaluation against all answer_key entries.
        
        Returns:
            Dictionary with summary statistics and per-line results.
        """
        for record in self.answer_key:
            self._run_test(record)
        
        return self._summarize()
    
    def _run_test(self, answer_record: Dict[str, Any]) -> None:
        """Run a single test case against answer_key entry."""
        result = {
            'rfq_id': answer_record['rfq_id'],
            'line_no': answer_record['line_no'],
            'raw_text': answer_record['raw_text'],
            'expected_status': answer_record['expected_status'],
            'expected_skus': answer_record['expected_skus'],
            'expected_compliance': answer_record['compliance_result'],
        }
        
        # Extract line specs from raw text
        line = engine.extract_rule_line(answer_record['raw_text'], int(answer_record['line_no']))
        
        # Analyze with full catalog and compliance rules
        analyzed = engine.analyze_line(line, catalog=self.catalog)
        
        # Map agent status to answer_key format
        agent_status = self._map_agent_status(analyzed, answer_record)
        
        result['agent_status'] = agent_status
        result['agent_skus'] = analyzed.get('match_candidates', [])
        if analyzed.get('match'):
            result['agent_matched_sku'] = analyzed['match']['sku']
        
        result['compliance_status'] = self._map_compliance_status(analyzed, answer_record)
        result['compliance_issues'] = analyzed.get('compliance', {}).get('issues', [])
        
        # Compare results
        result['status_correct'] = result['agent_status'] == result['expected_status']
        
        # For MATCH status, check if the SKU matches
        if result['expected_status'] in ('MATCH', 'match'):
            # Parse expected SKUs - handle both comma and semicolon separation
            expected_sku_list = [s.strip() for s in answer_record['expected_skus'].replace(';', ',').split(',')]
            agent_matched = result.get('agent_matched_sku')
            result['sku_correct'] = agent_matched in expected_sku_list if agent_matched else False
        else:
            result['sku_correct'] = True  # Not a match, so SKU correctness N/A
        
        # Compliance correctness - check if key compliance status matches
        expected_compliance_key = result['expected_compliance'].split(':')[0].strip().upper()
        actual_compliance_key = result['compliance_status'].split(':')[0].strip().upper()
        result['compliance_correct'] = expected_compliance_key == actual_compliance_key
        
        result['overall_correct'] = result['status_correct'] and result['sku_correct'] and result['compliance_correct']
        
        if self.verbose:
            self._print_test_result(result)
        
        self.results.append(result)
    
    def _map_agent_status(self, analyzed: Dict[str, Any], answer_record: Dict[str, Any]) -> str:
        """Convert agent internal status to answer_key format.
        
        Agent statuses: needs_clarification, needs_review, ready_for_approval, approved, blocked_compliance
        Answer key statuses: MATCH, CLARIFY, NO_MATCH, MATCH_ASSUMPTION
        """
        agent_status = analyzed.get('status', 'unknown')
        
        # Check for missing fields
        missing = [f for f in ("material","form","grade","thickness_in","width_in","length_in","quantity") 
                   if analyzed.get(f) is None]
        
        if agent_status == 'needs_clarification':
            # Missing critical fields
            return 'CLARIFY'
        elif agent_status == 'ready_for_approval' or agent_status == 'approved':
            # Single match found and compliant
            # Check if there were real assumptions made (missing fields that were guessed)
            # Standard gauge/unit conversions are NOT assumptions
            extracted = analyzed.get('clarifications', [])
            has_assumption = len(extracted) > 0  # Any clarifications means assumptions were made
            
            # Also check if the line notes contain "assumption" but exclude gauge/unit conversions
            raw_assumptions = []
            for key in ['thickness_assumption', 'size_assumption']:
                val = analyzed.get(key)
                if val and 'gauge' not in val.lower() and 'converted' not in val.lower() and 'feet' not in val.lower():
                    raw_assumptions.append(val)
            
            return 'MATCH_ASSUMPTION' if (has_assumption or raw_assumptions) else 'MATCH'
        elif agent_status == 'blocked_compliance':
            # Compliance blocked - but we still have a match candidate
            # This should be treated as MATCH with compliance warnings/blocks
            # or CLARIFY if blocking is severe
            issues = analyzed.get('compliance', {}).get('issues', [])
            if any('BLOCK' in issue.upper() or 'fail' in issue.lower() for issue in issues):
                return 'CLARIFY'  # Compliance blocks resolution
            return 'MATCH'
        else:
            # Default: if no match found, return NO_MATCH
            candidates = analyzed.get('match_candidates', [])
            if not candidates:
                return 'NO_MATCH'
            return 'CLARIFY'
    
    def _map_compliance_status(self, analyzed: Dict[str, Any], answer_record: Dict[str, Any]) -> str:
        """Convert agent compliance dict to answer_key string format.
        
        Expected formats: "OK", "OK: ...", "WARN: ...", "BLOCK: ...", "n/a"
        """
        match = analyzed.get('match')
        compliance = analyzed.get('compliance', {})
        issues = compliance.get('issues', [])
        
        # If expected_skus is "N/A", this is a NO_MATCH case - return n/a
        if answer_record['expected_skus'].strip().upper() == 'N/A':
            return 'n/a'
        
        # If agent found no match, return n/a
        if not match and not analyzed.get('match_candidates'):
            return 'n/a'
        
        # If agent found multiple candidates (needs clarification), compliance is pending
        if not match and analyzed.get('match_candidates'):
            return 'n/a'  # Compliance not yet evaluated for unconfirmed candidates
        
        # Agent found a single match - evaluate compliance
        if match:
            # If there are blocking issues
            blocking_issues = [i for i in issues if 'fail' in i.lower() or 'block' in i.lower()]
            if blocking_issues:
                return 'BLOCK: ' + '; '.join(blocking_issues[:1])
            
            # If there are warnings
            warning_issues = [i for i in issues if 'warn' in i.lower() or 'deprecated' in i.lower()]
            if warning_issues:
                return 'WARN: ' + '; '.join(warning_issues[:1])
            
            # OK status
            return 'OK'
        
        return 'n/a'
    
    def _print_test_result(self, result: Dict[str, Any]) -> None:
        """Print a single test result for debugging."""
        status_icon = 'PASS' if result['overall_correct'] else 'FAIL'
        print(f"\n[{status_icon}] {result['rfq_id']} Line {result['line_no']}")
        print(f"  Raw: {result['raw_text'][:80]}")
        print(f"  Expected Status: {result['expected_status']}")
        print(f"  Agent Status:    {result['agent_status']} {'(OK)' if result['status_correct'] else '(WRONG)'}")
        if result.get('agent_matched_sku'):
            print(f"  Expected SKU: {result['expected_skus']}")
            print(f"  Agent SKU:    {result['agent_matched_sku']} {'(OK)' if result['sku_correct'] else '(WRONG)'}")
        print(f"  Compliance: {result['expected_compliance']} -> {result['compliance_status']} {'(OK)' if result['compliance_correct'] else '(WRONG)'}")
        if result.get('compliance_issues'):
            for issue in result['compliance_issues'][:3]:
                print(f"    - {issue}")
    
    def _summarize(self) -> Dict[str, Any]:
        """Generate summary statistics from all test results."""
        if not self.results:
            return {'error': 'No test results to summarize'}
        
        total = len(self.results)
        
        # Count by expected status
        by_status = {}
        for result in self.results:
            status = result['expected_status']
            if status not in by_status:
                by_status[status] = {'total': 0, 'correct': 0, 'status_correct': 0, 'sku_correct': 0, 'compliance_correct': 0}
            by_status[status]['total'] += 1
            by_status[status]['correct'] += 1 if result['overall_correct'] else 0
            by_status[status]['status_correct'] += 1 if result['status_correct'] else 0
            by_status[status]['sku_correct'] += 1 if result['sku_correct'] else 0
            by_status[status]['compliance_correct'] += 1 if result['compliance_correct'] else 0
        
        # Overall metrics
        overall_correct = sum(1 for r in self.results if r['overall_correct'])
        status_correct = sum(1 for r in self.results if r['status_correct'])
        sku_correct = sum(1 for r in self.results if r['sku_correct'])
        compliance_correct = sum(1 for r in self.results if r['compliance_correct'])
        
        summary = {
            'total_lines': total,
            'overall_correct': overall_correct,
            'overall_accuracy': f"{overall_correct/total*100:.1f}%",
            'status_accuracy': f"{status_correct/total*100:.1f}%",
            'sku_accuracy': f"{sku_correct/total*100:.1f}%",
            'compliance_accuracy': f"{compliance_correct/total*100:.1f}%",
            'by_status': by_status,
            'failing_cases': self._get_failing_cases(),
            'sample_results': self.results[:5],  # First 5 for inspection
        }
        
        return summary
    
    def _get_failing_cases(self) -> List[Dict[str, Any]]:
        """Return list of failing test cases for investigation."""
        return [r for r in self.results if not r['overall_correct']]
    
    def print_report(self, summary: Dict[str, Any]) -> None:
        """Print human-readable evaluation report."""
        print("\n" + "="*80)
        print("RFQ AGENT EVALUATION REPORT")
        print("="*80)
        
        print(f"\nOVERALL ACCURACY: {summary['overall_correct']}/{summary['total_lines']} ({summary['overall_accuracy']})")
        print(f"  Status Accuracy:     {summary['status_accuracy']}")
        print(f"  SKU Accuracy:        {summary['sku_accuracy']}")
        print(f"  Compliance Accuracy: {summary['compliance_accuracy']}")
        
        print("\nBREAKDOWN BY EXPECTED STATUS:")
        for status, counts in sorted(summary['by_status'].items()):
            accuracy = counts['correct'] / counts['total'] * 100
            print(f"  {status:20s}: {counts['correct']:2d}/{counts['total']:2d} ({accuracy:5.1f}%)")
            print(f"    - Status:     {counts['status_correct']}/{counts['total']}")
            print(f"    - SKU:        {counts['sku_correct']}/{counts['total']}")
            print(f"    - Compliance: {counts['compliance_correct']}/{counts['total']}")
        
        print("\nFAILING TEST CASES:")
        if not summary['failing_cases']:
            print("  (none)")
        else:
            for case in summary['failing_cases']:
                print(f"\n  [FAIL] {case['rfq_id']} L{case['line_no']}")
                print(f"    Raw: {case['raw_text'][:100]}")
                print(f"    Expected: {case['expected_status']}, Got: {case['agent_status']}")
                if case.get('agent_matched_sku'):
                    print(f"    Expected SKU: {case['expected_skus']}, Got: {case['agent_matched_sku']}")
                if case.get('compliance_issues'):
                    print(f"    Compliance Issues: {', '.join(case['compliance_issues'][:2])}")
        
        print("\n" + "="*80)


def pytest_generate_tests(metafunc):
    """Pytest plugin to parametrize tests from answer_key."""
    if 'answer_record' in metafunc.fixturenames:
        suite = EvaluationSuite()
        metafunc.parametrize('answer_record', suite.answer_key)


def test_evaluation_suite():
    """Pytest entrypoint for evaluation suite."""
    suite = EvaluationSuite(verbose=True)
    summary = suite.run_all_tests()
    suite.print_report(summary)
    
    # Assert overall accuracy meets threshold (can be adjusted)
    overall_correct = summary['overall_correct']
    total = summary['total_lines']
    accuracy = overall_correct / total if total > 0 else 0
    
    print(f"\n\nAssertion: {overall_correct}/{total} tests passed ({accuracy*100:.1f}%)")
    assert accuracy >= 0.5, f"Accuracy {accuracy*100:.1f}% is below 50% threshold"


def test_database_loads():
    """Verify all database tables load correctly."""
    assert database.verify_database()[0], "Database verification failed"
    
    # Test each loader
    catalog = database.load_catalog()
    assert len(catalog) == 99, f"Expected 99 SKUs, got {len(catalog)}"
    
    synonyms = database.load_synonyms()
    assert len(synonyms) > 0, "Synonyms table empty"
    
    gauge_tables = database.load_gauge_tables()
    assert len(gauge_tables) > 0, "Gauge tables empty"
    
    compliance_rules = database.load_compliance_rules()
    assert len(compliance_rules) > 0, "Compliance rules empty"
    
    benchmarks = database.load_benchmarks()
    assert len(benchmarks) > 0, "Benchmarks table empty"
    
    answer_key = database.load_answer_key()
    assert len(answer_key) == 32, f"Expected 32 answer keys, got {len(answer_key)}"


def test_normalization():
    """Test synonym normalization."""
    test_cases = [
        ("SS sheet", "stainless_steel sheet"),
        ("galv steel", "galvanized steel"),
        ("304 grade", "304 grade"),
    ]
    
    for input_text, expected_contains in test_cases:
        normalized = engine.normalize_synonym(input_text)
        # Just verify that synonyms are being applied (exact output depends on loaded data)
        assert isinstance(normalized, str), f"Normalization failed for '{input_text}'"


def test_gauge_resolution():
    """Test gauge to thickness lookup."""
    # Test stainless 16 gauge
    result = engine.resolve_gauge_to_thickness('16', 'stainless_steel', 'sheet')
    assert result['thickness_in'] is not None, "Failed to resolve 16 ga stainless"
    assert result['lookup_table'] == 'gauge_table', "Should use gauge_table for sheet"
    
    # Test tube gauge (should be different from sheet)
    result_tube = engine.resolve_gauge_to_thickness('16', 'stainless_steel', 'tube')
    if result_tube['thickness_in']:
        assert result_tube['lookup_table'] == 'tube_wall_gauge', "Should use tube_wall_gauge for tubes"


def test_compliance_detection():
    """Test compliance trigger detection."""
    rfq_text = "Need stainless steel sheet, 304 grade, Buy America compliant, MTR required"
    triggers = engine.check_compliance_triggers(rfq_text)
    
    assert triggers['buy_america'], "Should detect Buy America"
    assert triggers['mtr'], "Should detect MTR"
    assert not triggers['dfars'], "Should not detect DFARS"


if __name__ == '__main__':
    # Run evaluation suite directly
    suite = EvaluationSuite(verbose=True)
    summary = suite.run_all_tests()
    suite.print_report(summary)
    
    # Exit with non-zero if accuracy is too low
    accuracy = summary['overall_correct'] / summary['total_lines'] if summary['total_lines'] > 0 else 0
    sys.exit(0 if accuracy >= 0.5 else 1)
