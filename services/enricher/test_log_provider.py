"""
Unit tests for LogProvider and factory function.
"""

import pytest
from unittest.mock import MagicMock
from log_provider import (
    NoneLogProvider,
    PodLogProvider,
    LokiLogProvider,
    get_log_provider
)


class TestNoneLogProvider:
    """Test NoneLogProvider (always returns None)."""
    
    def test_returns_none(self):
        provider = NoneLogProvider()
        result = provider.get_logs("default", "my-pod")
        assert result is None
    
    def test_returns_none_for_invalid_input(self):
        provider = NoneLogProvider()
        result = provider.get_logs("", "")
        assert result is None


class TestPodLogProvider:
    """Test PodLogProvider (Kubernetes API)."""
    
    def test_fetch_logs_success(self):
        # Mock core API
        mock_core = MagicMock()
        mock_core.read_namespaced_pod_log.return_value = "container output\nerror message"
        
        provider = PodLogProvider(mock_core, max_lines=200)
        result = provider.get_logs("default", "my-pod")
        
        assert result == "container output\nerror message"
        mock_core.read_namespaced_pod_log.assert_called_once()
    
    def test_handles_403_rbac_gracefully(self):
        # Mock core API with 403 error
        mock_core = MagicMock()
        mock_core.read_namespaced_pod_log.side_effect = Exception(
            "403: Forbidden - cannot get resource \"pods/log\""
        )
        
        provider = PodLogProvider(mock_core)
        result = provider.get_logs("default", "my-pod")
        
        assert result is None  # Returns None, not crash
    
    def test_handles_404_gracefully(self):
        # Mock core API with 404 error
        mock_core = MagicMock()
        mock_core.read_namespaced_pod_log.side_effect = Exception("404: Not Found")
        
        provider = PodLogProvider(mock_core)
        result = provider.get_logs("default", "missing-pod")
        
        assert result is None  # Returns None, not crash
    
    def test_handles_general_error_gracefully(self):
        # Mock core API with generic error
        mock_core = MagicMock()
        mock_core.read_namespaced_pod_log.side_effect = Exception("Network error")
        
        provider = PodLogProvider(mock_core)
        result = provider.get_logs("default", "my-pod")
        
        assert result is None  # Returns None, not crash
    
    def test_truncates_oversized_logs(self):
        # Mock core API returning large logs
        mock_core = MagicMock()
        large_output = "x" * 200000  # 200KB
        mock_core.read_namespaced_pod_log.return_value = large_output
        
        provider = PodLogProvider(mock_core)
        result = provider.get_logs("default", "my-pod")
        
        # Should be truncated to max_bytes (100000 by default)
        assert len(result) < len(large_output)
        assert "[... truncated ...]" in result


class TestLokiLogProvider:
    """Test LokiLogProvider (placeholder)."""
    
    def test_returns_none_not_implemented(self):
        provider = LokiLogProvider(
            endpoint="https://loki.example.com:3100",
            tenant_id="phylaxor"
        )
        result = provider.get_logs("default", "my-pod")
        assert result is None  # Placeholder, not implemented yet


class TestFactory:
    """Test get_log_provider factory function."""
    
    def test_factory_returns_none_provider(self):
        provider = get_log_provider("none")
        assert isinstance(provider, NoneLogProvider)
    
    def test_factory_returns_none_by_default(self):
        provider = get_log_provider("")
        assert isinstance(provider, NoneLogProvider)
    
    def test_factory_returns_podlogs_provider(self):
        mock_core = MagicMock()
        provider = get_log_provider("podlogs", core_api=mock_core)
        assert isinstance(provider, PodLogProvider)
    
    def test_factory_returns_loki_provider(self):
        provider = get_log_provider("loki")
        assert isinstance(provider, LokiLogProvider)
    
    def test_factory_raises_on_missing_core_api_for_podlogs(self):
        with pytest.raises(ValueError) as exc_info:
            get_log_provider("podlogs", core_api=None)
        assert "core_api required" in str(exc_info.value)
    
    def test_factory_raises_on_invalid_mode(self):
        with pytest.raises(ValueError) as exc_info:
            get_log_provider("invalid_mode")
        assert "Invalid logs mode" in str(exc_info.value)
    
    def test_factory_case_insensitive(self):
        provider = get_log_provider("NONE")
        assert isinstance(provider, NoneLogProvider)
        
        mock_core = MagicMock()
        provider = get_log_provider("PODLOGS", core_api=mock_core)
        assert isinstance(provider, PodLogProvider)
