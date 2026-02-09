# Phylaxor AI Agent Contract

**Version:** 1.0.0 (DRAFT)
**Date:** 2026-02-09
**Status:** PROPOSED

## 1. Overview

This document defines the strict integration contract between the Phylaxor Decision Engine (Backend) and the AI Agent (LLM). This contract is designed to be **read-only**, **safe**, and **extensible** for future agentic capabilities (tool calling).

The interaction model is currently **Single-Shot**:
`Alert + Context -> AI -> Structured Diagnosis`

## 2. Terminology

- **Fingerprint**: Unique, deterministic identifier for an alert grouping (v1 hash).
- **Cluster Context**: Global state of the cluster (version, node counts).
- **Resource Context**: Specific details about the affected entity (Pod, Node, PVC).
- **Constraints**: Hard limits on what the AI is allowed to suggest or do.

---

## 3. AIRequest Definition

The `AIRequest` is the JSON payload sent TO the LLM. It aggregates all necessary context so the LLM can make a decision without further questions (in this MVP phase).

### Structure

```json
{
  "meta": {
    "request_id": "uuid-v4",
    "timestamp": "ISO8601-UTC",
    "schema_version": "1.0"
  },
  "alert": {
    "fingerprint": "v1:abc12345",
    "alertname": "KubePodCrashLoopBackOff",
    "severity": "critical",
    "status": "firing",
    "starts_at": "ISO8601",
    "labels": { ... },
    "annotations": { ... }
  },
  "context": {
    "cluster": {
        "platform": "k8s",
        "version": "v1.29.1",
        "nodes_summary": { "ready": 3, "total": 3 }
    },
    "resource": {
        "kind": "Pod",
        "namespace": "payment-api",
        "name": "payment-processor-7f4d",
        "status": {
            "phase": "Running",
            "containers_ready": "0/1",
            "restarts": 15
        },
        "logs": [
            "2024-02-09T10:00:01Z [ERROR] Connection refused to DB",
            "2024-02-09T10:00:02Z [FATAL] Panic: db_init failed"
        ],
        "events": [
            { "type": "Warning", "reason": "BackOff", "message": "Back-off restarting failed container", "count": 12 }
        ],
        "node_info": { ... }
    }
  },
  "decision_context": {
    "source": "knowledge_base",
    "confidence_score": 0.85,
    "previous_matches": []
  },
  "constraints": {
    "read_only": true,
    "allow_exec": false,
    "max_tokens": 2048
  }
}
```

### JSON Schema (AIRequest)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AIRequest",
  "type": "object",
  "required": ["meta", "alert", "context", "constraints"],
  "properties": {
    "meta": {
      "type": "object",
      "required": ["request_id", "timestamp"],
      "properties": {
        "request_id": { "type": "string", "format": "uuid" },
        "timestamp": { "type": "string", "format": "date-time" },
        "schema_version": { "type": "string" }
      }
    },
    "alert": {
      "type": "object",
      "required": ["fingerprint", "alertname", "status"],
      "properties": {
        "fingerprint": { "type": "string" },
        "alertname": { "type": "string" },
        "severity": { "type": "string" },
        "status": { "type": "string" },
        "starts_at": { "type": "string" },
        "labels": { "type": "object" },
        "annotations": { "type": "object" }
      }
    },
    "context": {
      "type": "object",
      "properties": {
        "cluster": { "type": "object" },
        "resource": {
          "type": "object",
          "properties": {
            "kind": { "type": "string" },
            "namespace": { "type": "string" },
            "name": { "type": "string" },
            "logs": { "type": "array", "items": { "type": "string" } },
            "events": { "type": "array", "items": { "type": "object" } }
          }
        }
      }
    },
    "constraints": {
      "type": "object",
      "required": ["read_only"],
      "properties": {
        "read_only": { "type": "boolean" },
        "no_secrets": { "type": "boolean" }
      }
    }
  }
}
```

---

## 4. AIResponse Definition

The `AIResponse` is the STRICT JSON output expected from the LLM. It focuses on structured triage and separating analysis from actionable steps.

### Structure

```json
{
  "summary": "Pod is crashing due to database connection failure.",
  "triage": {
    "severity": "critical",
    "confidence": "high",
    "category": "connectivity"
  },
  "hypotheses": [
    {
      "description": "Database credentials might be invalid or DB is down.",
      "evidence": "Log line: 'Connection refused to DB' and restart count > 10"
    }
  ],
  "recommended_actions": [
    {
      "action": "Check Database Status",
      "description": "Verify if the PostgreSQL statefulset is running.",
      "priority": "high"
    }
  ],
  "checks": [
    "kubectl get pods -n db-namespace",
    "kubectl logs deployment/payment-api"
  ],
  "fixes": [
    "1. If DB is down, scale it up.",
    "2. Verify Secret 'db-creds' exists."
  ],
  "missing_info": [
    "NetworkPolicy configurations"
  ],
  "safety_notes": "Do not restart the database if it is performing a backup.",
  "suggested_tool_calls": [],
  "usage": {
    "completion_tokens": 150,
    "model": "gpt-4-turbo"
  }
}
```

### JSON Schema (AIResponse)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AIResponse",
  "type": "object",
  "required": ["summary", "triage", "hypotheses", "recommended_actions", "checks"],
  "properties": {
    "summary": { "type": "string", "maxLength": 300 },
    "triage": {
      "type": "object",
      "required": ["severity", "confidence"],
      "properties": {
        "severity": { "type": "string", "enum": ["critical", "warning", "info", "unknown"] },
        "confidence": { "type": "string", "enum": ["high", "medium", "low"] },
        "category": { "type": "string" }
      }
    },
    "hypotheses": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["description", "evidence"],
        "properties": {
          "description": { "type": "string" },
          "evidence": { "type": "string" }
        }
      }
    },
    "recommended_actions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["action", "description"],
        "properties": {
          "action": { "type": "string" },
          "description": { "type": "string" },
          "priority": { "type": "string", "enum": ["high", "medium", "low"] }
        }
      }
    },
    "checks": {
      "type": "array",
      "items": { "type": "string" },
      "description": "List of read-only kubectl commands"
    },
    "fixes": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Step-by-step generic runbook instructions"
    },
    "missing_info": {
      "type": "array",
      "items": { "type": "string" }
    },
    "safety_notes": { "type": "string" },
    "suggested_tool_calls": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["tool", "arguments"],
        "properties": {
          "tool": { "type": "string" },
          "arguments": { "type": "object" },
          "reason": { "type": "string" }
        }
      }
    },
    "usage": {
      "type": "object",
      "properties": {
        "completion_tokens": { "type": "integer" },
        "cost_estimate": { "type": "number" },
        "model": { "type": "string" }
      }
    }
  }
}
```

---

## 5. Examples

### Example 1: Simple Alert (No Logs)

**Scenario:** A `KubeNodeNotReady` alert for a worker node.

**AIRequest (Snippet):**
```json
{
  "alert": {
    "alertname": "KubeNodeNotReady",
    "fingerprint": "v1:node-xyz",
    "status": "firing",
    "labels": { "node": "worker-01", "severity": "warning" }
  },
  "context": {
    "resource": {
        "kind": "Node",
        "name": "worker-01",
        "status": {
            "conditions": [
                { "type": "Ready", "status": "False", "reason": "KubeletStopped", "message": "Kubelet has stopped posting status" }
            ]
        }
    }
  }
}
```

**AIResponse:**
```json
{
  "summary": "Node worker-01 is NotReady because Kubelet has stopped posting status.",
  "triage": {
    "severity": "warning",
    "confidence": "high",
    "category": "infrastructure"
  },
  "hypotheses": [
    {
      "description": "The Kubelet service on the node might be crashed or stopped.",
      "evidence": "Node condition Ready=False with reason KubeletStopped."
    }
  ],
  "recommended_actions": [
    {
      "action": "Investigate Node Status",
      "description": "Check if the node is accessible via SSH or cloud console.",
      "priority": "high"
    }
  ],
  "checks": [
    "kubectl describe node worker-01",
    "kubectl get events --field-selector involvedObject.kind=Node,involvedObject.name=worker-01"
  ],
  "fixes": [
    "1. SSH into worker-01.",
    "2. Check kubelet status: 'systemctl status kubelet'.",
    "3. Restart kubelet: 'systemctl restart kubelet'."
  ],
  "missing_info": [],
  "safety_notes": "Drain the node before performing any kernel upgrades or reboots.",
  "suggested_tool_calls": []
}
```

### Example 2: Application Crash (Repetitive Logs)

**Scenario:** A Java application crashing with OOM or RuntimeException.

**AIRequest (Snippet):**
```json
{
  "alert": {
    "alertname": "KubePodCrashLoopBackOff",
    "fingerprint": "v1:checkout-service",
    "status": "firing"
  },
  "context": {
    "resource": {
        "kind": "Pod",
        "name": "checkout-7d8b9",
        "logs": [
            "2024-02-09 12:00:01 INFO Starting App",
            "2024-02-09 12:00:05 ERROR java.lang.OutOfMemoryError: Java heap space",
            "2024-02-09 12:00:05 FATAL Uncaught exception in main thread"
        ]
    }
  }
}
```

**AIResponse:**
```json
{
  "summary": "Pod checkout-7d8b9 is crashing due to Java OutOfMemoryError.",
  "triage": {
    "severity": "critical",
    "confidence": "high",
    "category": "application"
  },
  "hypotheses": [
    {
      "description": "The application is exceeding its configured heap size.",
      "evidence": "Log contains 'java.lang.OutOfMemoryError: Java heap space'."
    }
  ],
  "recommended_actions": [
    {
      "action": "Increase Memory Limits",
      "description": "Adjust the resources.limits.memory in the deployment.",
      "priority": "high"
    }
  ],
  "checks": [
    "kubectl get pod checkout-7d8b9 -o yaml",
    "kubectl top pod checkout-7d8b9 --containers"
  ],
  "fixes": [
    "1. Edit deployment: kubectl edit deployment checkout-service",
    "2. Increase resources.limits.memory (e.g., from 512Mi to 1Gi).",
    "3. Verify JAVA_OPTS includes appropriate -Xmx settings."
  ],
  "missing_info": [
    "Current JVM Heap settings (JAVA_OPTS)"
  ],
  "safety_notes": "Ensure the node has enough capacity before increasing limits.",
  "suggested_tool_calls": [
    {
      "tool": "get_pod_resources",
      "arguments": { "namespace": "default", "pod": "checkout-7d8b9" },
      "reason": "To verify current resource limits vs usage."
    }
  ]
}
```
