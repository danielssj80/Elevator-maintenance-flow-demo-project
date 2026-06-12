# Step 6 Report — Endpoint Testing

- Date: 2026-06-12
- Change: deploy-aws-https

## Endpoints Tested

### GET /health
- Command: `curl -s http://localhost:8000/health`
- Status: 200 ✓
- Response: `{"status":"ok"}`

### GET /api/elevators — CORS allowed origin
- Command: `curl -s -H "Origin: http://localhost:5173" -I http://localhost:8000/api/elevators | grep -i access-control`
- Result: `access-control-allow-origin: http://localhost:5173` ✓

### GET /api/elevators — CORS disallowed origin
- Command: `curl -s -H "Origin: http://evil.example.com" -I http://localhost:8000/api/elevators | grep -i access-control`
- Result: no `Access-Control-Allow-Origin` header returned ✓

### GET /api/elevators — count
- Command: `curl -s http://localhost:8000/api/elevators | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d))"`
- Result: `100` ✓

## Outcome

PASS — CORS refactor works correctly: allowed origin gets header, unlisted origin gets nothing, fleet count unchanged.
