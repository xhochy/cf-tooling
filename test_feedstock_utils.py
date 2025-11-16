#!/usr/bin/env python3
"""
Simple validation tests for feedstock_utils module.

This script performs basic smoke tests to ensure the shared utilities
work correctly without making actual API calls or git operations.
"""

import sys
import tempfile
import os
from feedstock_utils import (
    get_current_version_from_recipe,
    check_version_needs_update
)


def test_get_current_version_from_recipe():
    """Test version extraction from recipe files."""
    print("Testing get_current_version_from_recipe()...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        recipe_dir = os.path.join(tmpdir, "recipe")
        os.makedirs(recipe_dir)
        
        # Test with meta.yaml (Jinja2 format)
        meta_yaml = os.path.join(recipe_dir, "meta.yaml")
        with open(meta_yaml, "w") as f:
            f.write('{% set version = "1.20.14" %}\n')
            f.write('{% set name = "go" %}\n')
        
        version = get_current_version_from_recipe(tmpdir)
        assert version == "1.20.14", f"Expected 1.20.14, got {version}"
        print("  ✓ meta.yaml (Jinja2 format)")
        
        # Test with recipe.yaml (newer format)
        os.remove(meta_yaml)
        recipe_yaml = os.path.join(recipe_dir, "recipe.yaml")
        with open(recipe_yaml, "w") as f:
            f.write('context:\n')
            f.write('  version: 20.11.0\n')
            f.write('  name: nodejs\n')
        
        version = get_current_version_from_recipe(tmpdir)
        assert version == "20.11.0", f"Expected 20.11.0, got {version}"
        print("  ✓ recipe.yaml (newer format)")
        
        # Test with no recipe files
        os.remove(recipe_yaml)
        version = get_current_version_from_recipe(tmpdir)
        assert version is None, f"Expected None, got {version}"
        print("  ✓ No recipe file returns None")


def test_check_version_needs_update():
    """Test version comparison logic."""
    print("\nTesting check_version_needs_update()...")
    
    # Test newer version available
    needs_update = check_version_needs_update("1.20.13", "1.20.14")
    assert needs_update is True, "Should need update for newer version"
    print("  ✓ Detects newer version")
    
    # Test same version
    needs_update = check_version_needs_update("1.20.14", "1.20.14")
    assert needs_update is False, "Should not need update for same version"
    print("  ✓ Skips same version")
    
    # Test older version
    needs_update = check_version_needs_update("1.20.15", "1.20.14")
    assert needs_update is False, "Should not need update for older version"
    print("  ✓ Skips older version")
    
    # Test with None current version
    needs_update = check_version_needs_update(None, "1.20.14")
    assert needs_update is True, "Should proceed with update when current version is unknown"
    print("  ✓ Proceeds when current version is None")


def main():
    """Run all validation tests."""
    print("=" * 60)
    print("Running feedstock_utils validation tests")
    print("=" * 60)
    print()
    
    try:
        test_get_current_version_from_recipe()
        test_check_version_needs_update()
        
        print("\n" + "=" * 60)
        print("✓ All validation tests passed!")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
