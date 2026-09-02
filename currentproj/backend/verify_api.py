from fastapi.testclient import TestClient
import main

client = TestClient(main.app)
response = client.post('/api/v1/disaster/predict-live-location', json={'latitude': 20.0, 'longitude': 85.0})
print('STATUS', response.status_code)
print('BODY_KEYS', sorted(response.json().keys()))
print('TIER', response.json()['analytics']['hazard_tier'])
print('PROB', response.json()['analytics']['flood_probability_pct'])
