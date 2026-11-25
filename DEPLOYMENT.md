# Deployment Information

## Public URL
https://agent-production-f110c215.up.railway.app

## Platform
Railway (project `day14-production-agent`, environment `production`, region `iad`)

| Service | Nguồn | Trạng thái |
| --- | --- | --- |
| `agent` | Agent Part 6, build từ `06-lab-complete/Dockerfile` (multi-stage) theo `06-lab-complete/railway.toml` (`healthcheckPath = "/health"`) | Online |
| `Redis` | Railway Redis database (`redis:8.2`, volume `redis-volume`) | Online |

### Cách deploy (Railway CLI, chạy trong thư mục `06-lab-complete/`)

```bash
railway login
railway init --name day14-production-agent
railway add --database redis
railway add --service agent \
  --variables "ENVIRONMENT=production" --variables "LOG_LEVEL=INFO" \
  --variables "AGENT_API_KEY=<secret>" --variables 'REDIS_URL=${{Redis.REDIS_URL}}' \
  --variables "RATE_LIMIT_PER_MINUTE=10" --variables "DAILY_BUDGET_USD=1.0" --variables "MONTHLY_BUDGET_USD=10.0"
railway up --service agent --ci
railway domain --service agent
```

## Test Commands (4 lệnh kiểm tra CP6)

Đặt `BASE=https://agent-production-f110c215.up.railway.app` và `AGENT_API_KEY=<key đặt trên Railway>`:

```bash
# 1. Health check → 200
curl -sS -w '  -> %{http_code}\n' "$BASE/health"

# 2. Readiness check (Redis kết nối qua REDIS_URL) → 200
curl -sS -w '  -> %{http_code}\n' "$BASE/ready"

# 3. /ask không có API key → 401
curl -sS -w '  -> %{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"cp6-test","question":"Hello"}'

# 4. /ask có X-API-Key hợp lệ → 200
curl -sS -w '  -> %{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"user_id":"cp6-test","question":"Hello"}'

# 5. Rate limit: gọi liên tiếp, vượt 10 req/phút → 429
for i in $(seq 1 12); do
  curl -s -o /dev/null -w '%{http_code} ' -X POST "$BASE/ask" \
    -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" \
    -d '{"user_id":"cp6-test","question":"Hello"}'
done; echo
```

### Kết quả thực tế (2026-11-25 23:25 GMT+7, xem `screenshots/test.png`)

```text
# 1. GET /health
{"status":"ok","environment":"production"}  -> HTTP 200

# 2. GET /ready
{"status":"ready"}  -> HTTP 200

# 3. POST /ask (không có X-API-Key)
{"detail":"Invalid or missing X-API-Key"}  -> HTTP 401

# 4. POST /ask (có X-API-Key)
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"input_tokens":1,"output_tokens":16,"cost_usd":9.75e-06}}  -> HTTP 200

# 5. 12 request tiếp theo trong cùng 1 phút
200 200 200 200 200 200 200 200 200 429 429 429
```

Request thứ 11 trong cửa sổ 60 giây bị chặn `429` (request ở bước 4 là request thứ 1), đúng `RATE_LIMIT_PER_MINUTE=10`; state rate limit nằm trong Redis của Railway.

Kiểm tra tự động bằng script chấm:

```text
$ python check_production_ready.py --static-only --public-url https://agent-production-f110c215.up.railway.app
✅ 12. Public URL ready (Railway / Render config)
     ✅ Có railway.toml hoặc render.yaml (không chỉ toàn comment)
     ✅ railway.toml: builder + healthcheckPath = "/health"
     ✅ render.yaml: web service + healthCheckPath /health
     ✅ render.yaml: secret không ghi thẳng giá trị (generateValue / sync: false)
     ✅ App lắng nghe theo biến PORT do platform cấp
     ✅ Public URL: GET https://agent-production-f110c215.up.railway.app/health → 200
```

## Environment Variables Set (đặt trên Railway, không ghi giá trị thật vào Git)

| Biến | Giá trị / nguồn |
| --- | --- |
| `PORT` | Railway tự inject (app nghe `${PORT:-8000}`, log startup ghi `port=8080`) |
| `ENVIRONMENT` | `production` |
| `LOG_LEVEL` | `INFO` |
| `REDIS_URL` | `${{Redis.REDIS_URL}}`: tham chiếu tới service Redis qua private network `redis.railway.internal:6379` |
| `AGENT_API_KEY` | Secret ngẫu nhiên, chỉ đặt trên Railway |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `MONTHLY_BUDGET_USD` | `10.0` |

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png): `railway status`, `railway service list` (agent + Redis Online), log deploy JSON và `/health`, `/ready` trả 200
- [Test results](screenshots/test.png): 4 lệnh CP6 + rate limit 429
