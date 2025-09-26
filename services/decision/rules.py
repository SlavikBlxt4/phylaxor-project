def rule_for(evt):
    name = (evt.get("alertname") or "").lower()
    ns = evt.get("labels",{}).get("namespace","default")
    pod = evt.get("labels",{}).get("pod","")

    if "crashloop" in name:
        return {
          "rule_id":"crashloop_basic",
          "summary":"Pod in CrashLoopBackOff",
          "checks":[
            f"kubectl -n {ns} get pod {pod} -o wide",
            f"kubectl -n {ns} logs {pod} --previous",
            f"kubectl -n {ns} describe pod {pod}"
          ],
          "fixes":[
            "Review env vars and secrets",
            "Adjust readiness/liveness probes",
            "Verify imagePullSecrets and image tag"
          ]
        }

    if "imagepullbackoff" in name or "errimagepull" in name:
        return {
          "rule_id":"imagepull_basic",
          "summary":"Image pull failed",
          "checks":[
            f"kubectl -n {ns} describe pod {pod}",
            f"kubectl -n {ns} get secret"
          ],
          "fixes":[
            "Configure valid imagePullSecrets",
            "Check repository permissions and tag"
          ]
        }

    return None
