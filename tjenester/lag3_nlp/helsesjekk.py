import sys, requests
try:
    r = requests.get("http://localhost:8013/helse", timeout=5)
    sys.exit(0 if r.status_code == 200 else 1)
except Exception:
    sys.exit(1)
