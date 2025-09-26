import os, json, redis, time

r = redis.Redis(host=os.getenv("REDIS_HOST","redis"), port=6379, db=0)

# ajustar para que recopile contexto segun el cluster en el que se instale
CTX = {
  "platform": "k8s",
  "cluster": "minikube",
  "version": "1.32",
  "storage": "hostpath",
  "operators": ["prom-operator"]
}

def main():
    while True:
        item = r.brpop("phylaxor_raw", timeout=5)
        if not item:
            continue
        _, payload = item
        evt = json.loads(payload)
        evt["context"] = CTX
        r.lpush("phylaxor_enriched", json.dumps(evt))

if __name__ == "__main__":
    main()
