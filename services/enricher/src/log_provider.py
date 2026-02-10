"""
LogProvider interface and implementations for Phylaxor enricher.

Supports three modes:
  - none: no logs fetched
  - loki: centralized logging backend (placeholder for future)
  - podlogs: direct Kubernetes API pods/log
"""

import os
import sys
import traceback
from abc import ABC, abstractmethod
from typing import Optional


class LogProvider(ABC):
    """Abstract base class for log providers."""
    
    @abstractmethod
    def get_logs(self, namespace: str, pod: str) -> Optional[str]:
        """
        Fetch logs for a pod.
        
        Args:
            namespace: Kubernetes namespace
            pod: Pod name
            
        Returns:
            Log content (string) or None if unavailable
            If RBAC 403 or other errors occur, logs warning and returns None.
        """
        pass


class NoneLogProvider(LogProvider):
    """No logs provider (safest mode)."""
    
    def get_logs(self, namespace: str, pod: str) -> Optional[str]:
        """Returns None (no logs)."""
        return None


class PodLogProvider(LogProvider):
    """Direct Kubernetes API pods/log provider."""
    
    def __init__(self, core_api, max_lines: int = 500, lookback_seconds: int = 300, timeout: int = 5):
        """
        Initialize PodLogProvider.
        
        Args:
            core_api: Kubernetes CoreV1Api instance
            max_lines: maximum log lines to fetch (tail_lines parameter)
            lookback_seconds: how far back to fetch logs (sinceSeconds)
            timeout: request timeout in seconds
        """
        self.core_api = core_api
        self.max_lines = max_lines
        self.lookback_seconds = lookback_seconds
        self.timeout = timeout
    
    def get_logs(self, namespace: str, pod: str) -> Optional[str]:
        """Fetch logs via Kubernetes API pods/log endpoint."""
        if not namespace or not pod:
            return None
        
        try:
            log_content = self.core_api.read_namespaced_pod_log(
                name=pod,
                namespace=namespace,
                tail_lines=self.max_lines,
                since_seconds=self.lookback_seconds,
                _request_timeout=self.timeout
            )
            
            # Truncate if necessary (safety measure)
            max_bytes = int(os.getenv("PHYLAXOR_LOGS_MAX_BYTES", "100000"))
            if len(log_content) > max_bytes:
                log_content = log_content[-max_bytes:]
                log_content = f"[... truncated ...]\n{log_content}"
            
            return log_content
            
        except Exception as e:
            # Check if this is a 403 RBAC error
            error_str = str(e)
            if "403" in error_str or "Forbidden" in error_str:
                print(
                    f"[enricher] WARN: pods/log denied for pod {pod} in namespace {namespace}",
                    file=sys.stderr,
                    flush=True
                )
            elif "404" in error_str or "not found" in error_str.lower():
                print(
                    f"[enricher] WARN: pod {pod} not found in namespace {namespace}",
                    file=sys.stderr,
                    flush=True
                )
            else:
                print(
                    f"[enricher] WARN: error fetching logs for {namespace}/{pod}: {e}",
                    file=sys.stderr,
                    flush=True
                )
            
            return None


class LokiLogProvider(LogProvider):
    """Centralized Loki backend provider (placeholder for MVP)."""
    
    def __init__(self, endpoint: str = "", tenant_id: str = "", username: str = "", password: str = ""):
        """
        Initialize LokiLogProvider.
        
        Args:
            endpoint: Loki query API endpoint (e.g., https://loki.logging.svc.cluster.local:3100)
            tenant_id: Loki tenant ID
            username: Loki username (for basic auth)
            password: Loki password (for basic auth)
        """
        self.endpoint = endpoint
        self.tenant_id = tenant_id
        self.username = username
        self.password = password
    
    def get_logs(self, namespace: str, pod: str) -> Optional[str]:
        """
        Fetch logs via Loki API (placeholder).
        
        For MVP, return None. Future implementation will:
        1. Build LogQL query: {namespace="...", pod_name="..."}
        2. Query Loki endpoint
        3. Parse and format log lines
        """
        print(
            f"[enricher] INFO: Loki mode enabled but not yet implemented. Returning no logs for {namespace}/{pod}",
            file=sys.stderr,
            flush=True
        )
        return None


def get_log_provider(logs_mode: str, core_api=None) -> LogProvider:
    """
    Factory function to get the appropriate LogProvider based on mode.
    
    Args:
        logs_mode: "none", "loki", or "podlogs"
        core_api: Kubernetes CoreV1Api instance (required for podlogs mode)
        
    Returns:
        LogProvider instance
        
    Raises:
        ValueError: if invalid mode or missing required parameters
    """
    mode = (logs_mode or "none").lower().strip()
    
    if mode == "none":
        return NoneLogProvider()
    
    elif mode == "podlogs":
        if core_api is None:
            raise ValueError("core_api required for podlogs mode")
        
        max_lines = int(os.getenv("PHYLAXOR_LOGS_MAX_LINES", "500"))
        lookback_seconds = int(os.getenv("PHYLAXOR_LOGS_LOOKBACK", "300"))
        timeout = int(os.getenv("PHYLAXOR_LOGS_TIMEOUT", "5"))
        
        return PodLogProvider(
            core_api=core_api,
            max_lines=max_lines,
            lookback_seconds=lookback_seconds,
            timeout=timeout
        )
    
    elif mode == "loki":
        endpoint = os.getenv("PHYLAXOR_LOKI_ENDPOINT", "")
        tenant_id = os.getenv("PHYLAXOR_LOKI_TENANT_ID", "")
        username = os.getenv("PHYLAXOR_LOKI_USERNAME", "")
        password = os.getenv("PHYLAXOR_LOKI_PASSWORD", "")
        
        return LokiLogProvider(
            endpoint=endpoint,
            tenant_id=tenant_id,
            username=username,
            password=password
        )
    
    else:
        raise ValueError(f"Invalid logs mode: {mode}. Must be one of: none, loki, podlogs")
