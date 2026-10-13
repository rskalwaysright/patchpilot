from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class BenchmarkCase:
    case_id: str
    category: str
    title: str
    bug_description: str
    raw_traceback: Optional[str]
    target_faulty_file: str
    target_faulty_symbol: str
    files: Dict[str, str]  # path -> content
    reproduction_test: str
    regression_test: str
    ground_truth_patch: str
    is_ambiguous: bool = False
    expected_outcome: str = "VERIFIED"  # VERIFIED | INCONCLUSIVE


BENCHMARK_CASES: List[BenchmarkCase] = [
    # Case 1: Exception & Traceback bug (ZeroDivisionError)
    BenchmarkCase(
        case_id="case_01_zerodiv",
        category="traceback_exception",
        title="ZeroDivisionError on empty window average",
        bug_description="Calling window_average with an empty sequence crashes with ZeroDivisionError.",
        raw_traceback="""Traceback (most recent call last):
  File "calc/stats.py", line 6, in window_average
    return sum(values) / len(values)
ZeroDivisionError: division by zero""",
        target_faulty_file="calc/stats.py",
        target_faulty_symbol="window_average",
        files={
            "calc/stats.py": """def window_average(values):
    if len(values) == 0:
        return 0.0
    return sum(values) / len(values)
""".replace("if len(values) == 0:\n        return 0.0\n    ", ""),
            "tests/test_stats.py": """from calc.stats import window_average

def test_window_average_normal():
    assert window_average([2, 4, 6]) == 4.0

def test_window_average_empty():
    assert window_average([]) == 0.0
"""
        },
        reproduction_test="tests/test_stats.py::test_window_average_empty",
        regression_test="tests/test_stats.py::test_window_average_normal",
        ground_truth_patch="""--- a/calc/stats.py
+++ b/calc/stats.py
@@ -1,2 +1,4 @@
 def window_average(values):
+    if not values:
+        return 0.0
     return sum(values) / len(values)
""",
        is_ambiguous=False,
    ),

    # Case 2: Incorrect boundary condition (Off-by-one in binary search / slice)
    BenchmarkCase(
        case_id="case_02_boundary",
        category="boundary_condition",
        title="Off-by-one upper bound in paginate_items",
        bug_description="paginate_items excludes the last item on exact page boundaries because range slicing uses page * size - 1 instead of page * size.",
        raw_traceback=None,
        target_faulty_file="service/pagination.py",
        target_faulty_symbol="paginate_items",
        files={
            "service/pagination.py": """def paginate_items(items, page, size):
    start = (page - 1) * size
    end = page * size - 1
    return items[start:end]
""",
            "tests/test_pagination.py": """from service.pagination import paginate_items

def test_pagination_count():
    items = list(range(20))
    res = paginate_items(items, 1, 10)
    assert len(res) == 10
    assert res == list(range(10))

def test_pagination_page_two():
    items = list(range(20))
    res = paginate_items(items, 2, 10)
    assert len(res) == 10
"""
        },
        reproduction_test="tests/test_pagination.py::test_pagination_count",
        regression_test="tests/test_pagination.py::test_pagination_page_two",
        ground_truth_patch="""--- a/service/pagination.py
+++ b/service/pagination.py
@@ -2,3 +2,3 @@
     start = (page - 1) * size
-    end = page * size - 1
+    end = page * size
     return items[start:end]
""",
        is_ambiguous=False,
    ),

    # Case 3: Wrong variable or dictionary key usage
    BenchmarkCase(
        case_id="case_03_wrong_key",
        category="wrong_variable_usage",
        title="KeyError accessing token metadata",
        bug_description="parse_auth_token accesses 'token' key instead of 'access_token', throwing KeyError on valid payload.",
        raw_traceback="""Traceback (most recent call last):
  File "auth/token.py", line 5, in parse_auth_token
    token_str = header["token"]
KeyError: 'token'""",
        target_faulty_file="auth/token.py",
        target_faulty_symbol="parse_auth_token",
        files={
            "auth/token.py": """def parse_auth_token(header):
    if "access_token" in header:
        return header["token"]
    return None
""",
            "tests/test_auth.py": """from auth.token import parse_auth_token

def test_valid_token():
    assert parse_auth_token({"access_token": "secret_abc"}) == "secret_abc"

def test_missing_token():
    assert parse_auth_token({}) is None
"""
        },
        reproduction_test="tests/test_auth.py::test_valid_token",
        regression_test="tests/test_auth.py::test_missing_token",
        ground_truth_patch="""--- a/auth/token.py
+++ b/auth/token.py
@@ -2,2 +2,2 @@
     if "access_token" in header:
-        return header["token"]
+        return header["access_token"]
""",
        is_ambiguous=False,
    ),

    # Case 4: Logic error that does not crash immediately (silent incorrect result)
    BenchmarkCase(
        case_id="case_04_logic_tax",
        category="silent_logic_error",
        title="Incorrect discount calculation on discounted totals",
        bug_description="apply_discount adds the discount amount instead of subtracting it from the subtotal.",
        raw_traceback=None,
        target_faulty_file="billing/pricing.py",
        target_faulty_symbol="apply_discount",
        files={
            "billing/pricing.py": """def apply_discount(subtotal, discount_rate):
    if discount_rate <= 0:
        return subtotal
    discount_amount = subtotal * discount_rate
    return subtotal + discount_amount
""",
            "tests/test_pricing.py": """from billing.pricing import apply_discount

def test_zero_discount():
    assert apply_discount(100.0, 0.0) == 100.0

def test_ten_percent_discount():
    assert apply_discount(100.0, 0.10) == 90.0
"""
        },
        reproduction_test="tests/test_pricing.py::test_ten_percent_discount",
        regression_test="tests/test_pricing.py::test_zero_discount",
        ground_truth_patch="""--- a/billing/pricing.py
+++ b/billing/pricing.py
@@ -4,2 +4,2 @@
     discount_amount = subtotal * discount_rate
-    return subtotal + discount_amount
+    return subtotal - discount_amount
""",
        is_ambiguous=False,
    ),

    # Case 5: Ambiguous case where correct outcome is INCONCLUSIVE
    BenchmarkCase(
        case_id="case_05_ambiguous",
        category="ambiguous_inconclusive",
        title="Vague UI timeout report without traceback or repro steps",
        bug_description="The application sometimes feels sluggish when clicking buttons on Tuesday.",
        raw_traceback=None,
        target_faulty_file="core/app.py",
        target_faulty_symbol="run_loop",
        files={
            "core/app.py": """def run_loop():
    return True
""",
            "tests/test_app.py": """from core.app import run_loop

def test_loop():
    assert run_loop() is True
"""
        },
        reproduction_test="tests/test_app.py::test_loop",
        regression_test="tests/test_app.py::test_loop",
        ground_truth_patch="",
        is_ambiguous=True,
        expected_outcome="INCONCLUSIVE",
    ),

    # Case 6: Patch fixes one test but breaks another (Regression trap)
    BenchmarkCase(
        case_id="case_06_regression_trap",
        category="regression_trap",
        title="Sanitizer patch breaks unicode characters while fixing quotes",
        bug_description="sanitize_string should strip dangerous SQL quotes without stripping unicode non-ascii names.",
        raw_traceback=None,
        target_faulty_file="db/sanitize.py",
        target_faulty_symbol="sanitize_string",
        files={
            "db/sanitize.py": """def sanitize_string(val):
    return val.replace("'", "''")
""",
            "tests/test_sanitize.py": """from db.sanitize import sanitize_string

def test_quotes():
    assert sanitize_string("O'Reilly") == "O''Reilly"

def test_unicode():
    assert sanitize_string("René") == "René"
"""
        },
        reproduction_test="tests/test_sanitize.py::test_quotes",
        regression_test="tests/test_sanitize.py::test_unicode",
        ground_truth_patch="""--- a/db/sanitize.py
+++ b/db/sanitize.py
@@ -1,2 +1,2 @@
 def sanitize_string(val):
-    return val.replace("'", "''")
+    return "".join(c for c in val.replace("'", "''"))
""",
        is_ambiguous=False,
    ),
]
