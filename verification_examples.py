import json
from services.ingest.fingerprint import calculate_fingerprint

examples = [
    {
        "name": "CrashLoopBackOff for pod test-api in default",
        "alert": {
            "labels": {
                "alertname": "CrashLoopBackOff",
                "pod": "test-api-7f8c9d5d6b-abcde",
                "namespace": "default"
            }
        }
    },
    {
        "name": "KubePodCrashLooping for pod crashloop-xxx in phylaxor-test",
        "alert": {
            "labels": {
                "alertname": "KubePodCrashLooping",
                "pod": "crashloop-1234567890-abcde", 
                "namespace": "phylaxor-test"
            }
        }
    },
    {
        "name": "NodeNotReady node=crc",
        "alert": {
            "labels": {
                "alertname": "NodeNotReady",
                "node": "crc"
            }
        }
    },
    {
        "name": "ClusterOperatorDegraded name=kube-apiserver",
        "alert": {
            "labels": {
                "alertname": "ClusterOperatorDegraded",
                "name": "kube-apiserver"
            }
        }
    }
]

print("# Computed Fingerprint Examples\n")
for case in examples:
    fp, expl = calculate_fingerprint(case["alert"])
    print(f"## {case['name']}")
    print(f"- **Fingerprint**: `{fp}`")
    print(f"- **Scope**: `{expl['scope']}`")
    print(f"- **Entity**: `{expl['entity_value']}`")
    print(f"- **Inputs**: `{json.dumps(expl['inputs'], sort_keys=True)}`")
    print("")
