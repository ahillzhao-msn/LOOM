"""Integration tests for classify + soft_classify — all changed paths."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture(scope="module")
def dr():
    """DomainRegistry singleton (shared across tests for speed)."""
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
            assert isinstance(cid, int), f"{ent.name} → {type(cid).__name__}"

    def test_unknown_domain(self, dr):
        from kafed.knowledge.classify.soft_classify import _name_to_cluster_id
        cid = _name_to_cluster_id("NONEXISTENT_DOMAIN_XYZ")
        assert cid is None, f"Unknown domain should return None, got {cid}"


class TestLoadClusterCentroids:
    """_load_cluster_centroids must load from data, not hardcoded names."""

    def test_returns_centroids(self):
        from kafed.knowledge.classify.soft_classify import _load_cluster_centroids
        centroids = _load_cluster_centroids()
        # Should have the same number as cluster_mapping.json
        import json
        from kafed.config import get_config
        cm_path = get_config().data_dir / "cluster_mapping.json"
        cm = json.loads(cm_path.read_text())
        expected = len(cm.get("clusters", {}))
        assert len(centroids) == expected, f"Expected {expected} centroids, got {len(centroids)}"

    def test_centroids_are_ndarray(self):
        from kafed.knowledge.classify.soft_classify import _load_cluster_centroids
        centroids = _load_cluster_centroids()
        for i, c in enumerate(centroids):
            assert isinstance(c, np.ndarray), f"Centroid {i} is {type(c)}"
            assert c.shape == (384,), f"Centroid {i} shape is {c.shape}"

    def test_no_hardcoded_strings(self):
        """Verify the module source has zero hardcoded domain names."""
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
            # Must be a valid ChromaDB where filter
            if "$or" in result.search_filter:
                for clause in result.search_filter["$or"]:
                    assert "cluster_id" in clause
            elif "cluster_id" in result.search_filter:
                assert isinstance(result.search_filter["cluster_id"], int)

    def test_short_text(self, dr):
        from kafed.knowledge.classify.soft_classify import hierarchical_search
        result = hierarchical_search("test")
        assert result is not None


# ── classify: _infer_level_regex + _infer_type_regex ──────


class TestInferLevel:
    """_infer_level_regex: YAML patterns first, then generic fallback."""

    def test_l4_via_yaml(self):
        """SAP t-code patterns from YAML."""
        from kafed.knowledge.classify.classify import _infer_level_regex
        assert _infer_level_regex("IW22 创建维护订单") == "L4"
        assert _infer_level_regex("transaction code IW31") == "L4"
        assert _infer_level_regex("tcode VA02") == "L4"

    def test_l4_via_fallback(self):
        """Generic transaction code fallback."""
        from kafed.knowledge.classify.classify import _infer_level_regex
        assert _infer_level_regex("tcode VA02") == "L4"

    def test_l3_via_fallback(self):
        from kafed.knowledge.classify.classify import _infer_level_regex
        assert _infer_level_regex("如何创建采购订单") == "L3"
        assert _infer_level_regex("第一步点击创建") == "L3"

    def test_l2_via_fallback(self):
        from kafed.knowledge.classify.classify import _infer_level_regex
        assert _infer_level_regex("是什么是概念") == "L2"
        assert _infer_level_regex("difference between A and B") == "L2"

    def test_l1_default(self):
        from kafed.knowledge.classify.classify import _infer_level_regex
        assert _infer_level_regex("some random text without markers") == "L1"

    def test_no_hardcoded_tcode(self):
        """SAP-specific t-code pattern must NOT be in Python code."""
        import inspect
        from kafed.knowledge.classify import classify
        src = inspect.getsource(classify)
        # The SAP-specific patterns should only be in YAML, not inline in _infer_level_regex
        fn = classify._infer_level_regex
        fn_src = inspect.getsource(fn)
        assert "IW" not in fn_src or "YAML" in fn_src, "IW still hardcoded in _infer_level_regex!"


class TestInferType:
    """_infer_type_regex: YAML patterns first, then generic fallback."""

    def test_experiential_via_yaml(self):
        from kafed.knowledge.classify.classify import _infer_type_regex
        assert _infer_type_regex("注意不要删除这个") == "EXPERIENTIAL"

    def test_procedural_via_fallback(self):
        from kafed.knowledge.classify.classify import _infer_type_regex
        assert _infer_type_regex("点击保存按钮") == "PROCEDURAL"

    def test_declarative_default(self):
        from kafed.knowledge.classify.classify import _infer_type_regex
        assert _infer_type_regex("这是一个普通的声明") == "DECLARATIVE"


class TestClassify:
    """classify() end-to-end."""

    def test_domain_and_level(self):
        from kafed.knowledge.classify.classify import classify
        result = classify("IW31 create maintenance order")
        assert "domain" in result
        assert "level" in result
        assert "type" in result
        assert "method" in result
        assert result["level"] == "L4"

    def test_fallback_path(self):
        from kafed.knowledge.classify.classify import classify
        result = classify("completely random text about nothing specific")
        assert result["domain"]  # should not crash


# ── YAML loading ──────────────────────────────────────────


class TestYamlLoading:
    """seed_patterns.yaml must load correctly."""

    def test_levels_loaded(self):
        from kafed.knowledge.classify.classify import _load_level_type_patterns
        levels, types = _load_level_type_patterns()
        assert "L4" in levels
        assert "L3" in levels
        assert "L2" in levels
        assert len(levels["L4"]) >= 1

    def test_types_loaded(self):
        from kafed.knowledge.classify.classify import _load_level_type_patterns
        levels, types = _load_level_type_patterns()
        assert "EXPERIENTIAL" in types
        assert "REASONING" in types
        assert "PROCEDURAL" in types

    def test_settings_loaded(self):
        from kafed.knowledge.classify.classify import _load_settings
        settings = _load_settings()
        assert settings["embedding_score_threshold"] == 0.65
        assert settings["embedding_only_confidence_threshold"] == 0.85

    def test_seed_patterns_path_configurable(self):
        from kafed.config import get_config
        path = get_config().seed_patterns_path
        assert path is not None, "seed_patterns_path must be set in kafed.yaml"
        assert path.exists(), f"{path} does not exist"

    def test_no_seed_patterns_still_works(self):
        """Without YAML, classify should still work with fallbacks."""
        from kafed.knowledge.classify import classify as clm
        # Clear caches to force fresh load
        clm._settings_cache = None
        clm._LEVEL_YAML = None
        clm._TYPE_YAML = None

        orig_path = clm.get_config().seed_patterns_path
        try:
            with patch.object(clm, "get_config") as mock:
                dummy = type("Dummy", (), {"seed_patterns_path": None})()
                mock.return_value = dummy
                settings = clm._load_settings()
                assert settings["embedding_score_threshold"] == 0.65
                level = clm._infer_level_regex("如何")
                assert level == "L3", f"Expected L3, got {level}"
        finally:
            clm._settings_cache = None
            clm._LEVEL_YAML = None
            clm._TYPE_YAML = None
