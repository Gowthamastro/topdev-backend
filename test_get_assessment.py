import requests
import json

resp = requests.post("http://localhost:8000/api/v1/auth/login", data={"username": "admin@topdev.ai", "password": "Admin@123"})
token = resp.json().get("access_token")
if token:
    r = requests.get("http://localhost:8000/api/v1/assessments/job/22/details", headers={"Authorization": f"Bearer {token}"})
    try:
        data = r.json()
        print("Data keys:", data.keys())
        for k, v in data.items():
            if type(v) in [dict, list]:
                print(f"{k}: type={type(v)}, len={len(v)}")
            else:
                print(f"{k}: {v}")
    except Exception as e:
        print("Failed to parse JSON", r.text[:200])
