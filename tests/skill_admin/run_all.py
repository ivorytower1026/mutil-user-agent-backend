"""Run all skill admin tests.

Usage:
    uv run python tests/skill_admin/run_all.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.skill_admin.conftest import start_server, stop_server, cleanup_tmp_dir
from tests.skill_admin.test_auth import run_tests as run_auth_tests
from tests.skill_admin.test_upload import run_tests as run_upload_tests
from tests.skill_admin.test_list import run_tests as run_list_tests
from tests.skill_admin.test_retrieval import run_tests as run_retrieval_tests
from tests.skill_admin.test_validation import run_tests as run_validation_tests
from tests.skill_admin.test_approval import run_tests as run_approval_tests
from tests.skill_admin.test_rejection import run_tests as run_rejection_tests
from tests.skill_admin.test_deletion import run_tests as run_deletion_tests
from tests.skill_admin.test_report import run_tests as run_report_tests


def run_all_tests():
    """Run all skill admin tests."""
    print("=" * 70)
    print("v0.1.9 Skill Admin API - Integration Tests")
    print("=" * 70)
    print()
    print("Test Modules:")
    print("  1. Authentication (3 tests)")
    print("  2. Upload (4 tests)")
    print("  3. Listing (3 tests)")
    print("  4. Retrieval (2 tests)")
    print("  5. Validation (3 tests)")
    print("  6. Approval (2 tests)")
    print("  7. Rejection (3 tests)")
    print("  8. Deletion (2 tests)")
    print("  9. Report (2 tests)")
    print()
    print("Total: 24 test cases")
    print("=" * 70)
    
    print("\n[Setup] Starting server...")
    start_server()
    print("[Setup] Server started\n")
    
    all_results = []
    
    try:
        print("-" * 70)
        print("Phase 1: Authentication Tests")
        print("-" * 70)
        all_results.extend(run_auth_tests())
        
        print("\n" + "-" * 70)
        print("Phase 2: Upload Tests")
        print("-" * 70)
        all_results.extend(run_upload_tests())
        
        print("\n" + "-" * 70)
        print("Phase 3: Listing Tests")
        print("-" * 70)
        all_results.extend(run_list_tests())
        
        print("\n" + "-" * 70)
        print("Phase 4: Retrieval Tests")
        print("-" * 70)
        all_results.extend(run_retrieval_tests())
        
        print("\n" + "-" * 70)
        print("Phase 5: Validation Tests")
        print("-" * 70)
        all_results.extend(run_validation_tests())
        
        print("\n" + "-" * 70)
        print("Phase 6: Approval Tests")
        print("-" * 70)
        all_results.extend(run_approval_tests())
        
        print("\n" + "-" * 70)
        print("Phase 7: Rejection Tests")
        print("-" * 70)
        all_results.extend(run_rejection_tests())
        
        print("\n" + "-" * 70)
        print("Phase 8: Deletion Tests")
        print("-" * 70)
        all_results.extend(run_deletion_tests())
        
        print("\n" + "-" * 70)
        print("Phase 9: Report Tests")
        print("-" * 70)
        all_results.extend(run_report_tests())
        
    finally:
        print("\n[Cleanup] Stopping server...")
        stop_server()
        cleanup_tmp_dir()
        print("[Cleanup] Done")
    
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, r in all_results if r is True)
    failed = sum(1 for _, r in all_results if r is not True)
    
    print()
    for name, result in all_results:
        status = "PASS" if result is True else "FAIL"
        print(f"  [{status:^6}] {name}")
    
    print()
    print("-" * 70)
    print(f"Total: {len(all_results)} tests")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print("-" * 70)
    
    if failed == 0:
        print("\n*** ALL TESTS PASSED ***\n")
    else:
        print(f"\n*** {failed} TEST(S) FAILED ***\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
