"""Integration tests for classify + soft_classify — pure embedding-based (no regex)."""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture(scope="module")
def dr():
    from kafed.knowledge.classify.domain_registry import DomainRegistry
    return DomainRegistry.instance()


# ── soft_classify: _name_to_cluster_id ────────────────────

class TestNameToClusterId:
    """_name_to_cluster_id must work for ALL registered domains, with zero hardcoded names."""

    def test_all_domains_map(self, dr):
        from kafed.knowledge.classify.soft_classify import _name_to_cluster_id
        failures = [e.name for e in dr.entities if _name_to_cluster_id(e.name) is None]
        assert not failures, f"{len(failures)} domains failed: {failures[:5]}..."

    def test_returns_int(self, dr):
        from kafed.knowledge.classify.soft_classify import _name_to_cluster_id
        for ent in list(dr.entities)[:10]:
            cid = _name_to_cluster_id(ent.name)
            assert isinstance(cid, int), f"{ent.name} -> {type(cid).__name__}"

    def test_unknown_domain(self, dr):
        from kafed.knowledge.classify.soft_classify import _name_to_cluster_id
        cid = _name_to_cluster_id("NONEXISTENT_DOMAIN_XYZ")
        assert cid is None


class TestLoadClusterCentroids:
    """_load_cluster_centroids must load from data, not hardcoded names."""

    def test_returns_centroids(self):
        from kafed.knowledge.classify.soft_classify import _load_cluster_centroids
        import json
        from kafed.config import get_config
        centroids = _load_cluster_centroids()
        cm_path = get_config().data_dir / "cluster_mapping.json"
        cm = json.loads(cm_path.read_text())
        expected = len(cm.get("clusters", {}))
        assert len(centroids) == expected

    def test_centroids_are_ndarray(self):
        from kafed.knowledge.classify.soft_classify import _load_cluster_centroids
        centroids = _load_cluster_centroids()
        for i, c in enumerate(centroids):
            assert isinstance(c, np.ndarray), f"Centroid {i} is {type(c)}"
            assert c.shape == (384,)

    def test_no_hardcoded_strings(self):
        import inspect
        from kafed.knowledge.classify import soft_classify
        src = inspect.getsource(soft_classify)
        for bad in ["SAP_PM", "IID_GIS", "ARCFM", "Warehouse Management"]:
            assert bad not in src, f"Hardcoded string '{bad}' found in soft_classify.py!"


class TestHierarchicalSearch:
    """hierarchical_search must work end-to-end."""

    def test_returns_soft_result(self, dr):
        from kafed.knowledge.classify.soft_classify import hierarchical_search
        result = hierarchical_search("IW31 maintenance order create")
        assert result is not None
        assert len(result.candidates) > 0
        assert result.query == "IW31 maintenance order create"

    def test_search_filter_valid(self, dr):
        from kafed.knowledge.classify.soft_classify import hierarchical_search
        result = hierarchical_search("IW31 maintenance order create")
        if result.search_filter:
            if "$or" in result.search_filter:
                for clause in result.search_filter["$or"]:
                    assert "cluster_id" in clause
            elif "cluster_id" in result.search_filter:
                assert isinstance(result.search_filter["cluster_id"], int)

    def test_short_text(self, dr):
        from kafed.knowledge.classify.soft_classify import hierarchical_search
        result = hierarchical_search("test")
        assert result is not None


# ── classify: pure embedding ──────────────────────────────

class TestClassify:
    """classify() — embedding-only, no regex fallback."""

    def test_returns_structure(self):
        from kafed.knowledge.classify.classify import classify
        result = classify("IW31 create maintenance order")
        assert "domain" in result
        assert "level" in result
        assert "type" in result
        assert "method" in result
        assert result["method"] in ("embedding", "default")
        assert result["level"] in ("L1", "L2", "L3", "L4")
        assert result["type"] in ("DECLARATIVE", "PROCEDURAL", "EXPERIENTIAL", "REASONING")

    def test_any_text_returns_valid_result(self):
        """Even random text returns a valid classification (no crash)."""
        from kafed.knowledge.classify.classify import classify
        result = classify("xyzzy random gibberish not matching any domain")
        assert isinstance(result["domain"], str)
        assert result["domain"]  # non-empty
        assert result["method"] in ("embedding", "default")

    def test_no_regex_functions_remain(self):
        """Verify classify.py has zero regex-based fallback functions."""
        import inspect
        from kafed.knowledge.classify import classify as clm
        src = inspect.getsource(clm)
        assert "_infer_level_regex" not in src, "regex fallback still present!"
        assert "_infer_type_regex" not in src, "regex fallback still present!"
        assert "_infer_domain_regex" not in src, "regex fallback still present!"
        assert "_load_seed_patterns" not in src, "seed_patterns still referenced!"
