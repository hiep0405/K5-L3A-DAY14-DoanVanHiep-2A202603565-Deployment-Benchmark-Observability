# Day 14 Lab — Mission Answers

> **Học viên:** Đoàn Văn Hiệp (`K5-L3A`, MSSV `2A202603565`)
> **Môi trường thực hiện:** Windows 11 + WSL2 (`Ubuntu-24.04`) + Docker CE `29.10.1` + Docker Compose `v5.8.0` + Python `3.12` (Part 1, 2, 4, 5, 6 `PASS 12/12` và Part 7 đã chạy và đo trực tiếp; Part 3 deploy agent Part 6 lên Railway: `https://agent-production-f110c215.up.railway.app`).

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secret trong mã nguồn (`develop/app.py`, dòng 17–18):**
   - `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"`
   - `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`
   - Nếu push lên GitHub public, key và mật khẩu DB bị lộ ngay trong lịch sử Git.
   - Bản `production/config.py` (dòng 27–32) đã sửa bằng `os.getenv("OPENAI_API_KEY", "")` và `os.getenv("AGENT_API_KEY", "")`, kèm `Settings.validate()` để fail-fast nếu chạy `production` mà thiếu `AGENT_API_KEY`.
2. **Không quản lý cấu hình theo môi trường (`develop/app.py`, dòng 21–22):**
   - `DEBUG = True` và `MAX_TOKENS = 500` bị gắn cứng trong code.
   - Bản `production/config.py` (dòng 15–35) gom toàn bộ cấu hình vào dataclass `Settings` đọc từ biến môi trường.
3. **Dùng `print()` thay cho structured logging và làm lộ secret ra log (`develop/app.py`, dòng 33–38):**
   - `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` in thẳng API key ra stdout.
   - Bản `production/app.py` (dòng 28–32, 111–122) dùng `logging` định dạng JSON và chỉ log metadata như `question_length`, `client_ip`, `response_length`.
4. **Thiếu endpoint `/health` và `/ready` (`develop/app.py`, dòng 42–43):**
   - Nền tảng orchestrator/cloud không biết process còn sống hay đã sẵn sàng nhận traffic để restart hoặc điều hướng tải.
   - Bản `production/app.py` (dòng 135–161) bổ sung `GET /health` (liveness) và `GET /ready` (readiness, trả `503` nếu `not is_ready`).
5. **Hardcode `host="localhost"`, `port=8000`, `reload=True` (`develop/app.py`, dòng 49–54):**
   - `host="localhost"` không nhận được kết nối từ ngoài container; `port=8000` bỏ qua biến `$PORT` của cloud platform; `reload=True` gây tốn tài nguyên và không an toàn ở production.
   - Bản `production/app.py` (dòng 194–199) bind `settings.host` (`0.0.0.0`), `settings.port` (từ `PORT`), `reload=settings.debug`.
6. **Không có graceful shutdown và thiếu kiểm tra input chặt chẽ (`develop/app.py`, dòng 30–31):**
   - Không có `lifespan` hay xử lý `SIGTERM`, dễ cắt ngang request khi tắt/restart; route `/ask` nhận `question` qua query param và không giới hạn độ dài.
   - Bản `production/app.py` (dòng 39–68, 102–108, 180–189) dùng `lifespan`, bắt `SIGTERM` và nhận JSON body với kiểm tra rỗng (`422`).

### Exercise 1.2: Kết quả chạy thực tế bản `develop` và `production`

**Bản `01-localhost-vs-production/develop/app.py` (`POST /ask?question=Hello`):**
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 14:48:32 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

**Bản `01-localhost-vs-production/production/app.py` (`ENVIRONMENT=staging PORT=8000`):**
```http
# GET /health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":1.4,"version":"1.0.0","environment":"staging","timestamp":"2026-11-25T14:48:35.392549+00:00"}

# GET /ready
HTTP/1.1 200 OK
{"ready":true}

# POST /ask (JSON body)
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}
```

### Exercise 1.3: Bảng so sánh `develop` vs `production`

| Feature | Develop | Production | Tại sao quan trọng? |
| --- | --- | --- | --- |
| **Config** | Hardcode trong `app.py` (`DEBUG`, `MAX_TOKENS`, `port=8000`) | Đọc từ biến môi trường qua `config.py` (`Settings`) | Một artifact/image có thể chạy ở dev/staging/prod mà không phải sửa code (12-Factor III). |
| **Secrets** | Gán chuỗi trực tiếp (`OPENAI_API_KEY = "sk-..."`) và in ra log | Đọc từ env (`os.getenv`), không log secret, dùng `.env.example` làm mẫu | Tránh lộ key lên Git và log aggregator; dễ xoay vòng (rotate) secret khi bị lộ. |
| **Network binding** | `host="localhost"`, `port=8000`, `reload=True` | `host="0.0.0.0"`, `port=int(os.getenv("PORT", 8000))`, `reload=settings.debug` | Container và cloud (Railway/Render/Cloud Run) cần app lắng nghe trên `0.0.0.0:$PORT`. |
| **Health check** | Không có `/health`, `/ready` | Có `GET /health` (liveness) và `GET /ready` (readiness, 503 khi chưa sẵn sàng) | Platform biết khi nào cần restart container hỏng và chỉ route traffic khi app sẵn sàng. |
| **Logging** | `print("[DEBUG] ...")` tự do | Structured JSON logging (`time`, `level`, `msg`) | Dễ parse, tìm kiếm và liên kết sự cố trong Loki/Datadog/Cloud Logging. |
| **Shutdown** | Tắt đột ngột | `lifespan` + xử lý `SIGTERM` | Không cắt ngang request đang xử lý và đóng kết nối sạch trước khi thoát. |
| **CORS** | Không cấu hình | `CORSMiddleware` đọc `ALLOWED_ORIGINS` | Kiểm soát domain frontend được phép gọi API trên trình duyệt. |

---

## Part 2: Docker

### Exercise 2.1: Trả lời 4 câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image là gì?**
   - `python:3.11` (`FROM python:3.11` ở dòng 8) — bản Python đầy đủ kèm toolchain và nhiều thư viện hệ thống (~1 GB).
2. **Working directory là gì?**
   - `/app` (`WORKDIR /app` ở dòng 11) — mọi lệnh `COPY`, `RUN`, `CMD` sau đó thực thi tương đối từ `/app`.
3. **Tại sao `COPY 02-docker/develop/requirements.txt .` phải đứng trước `COPY 02-docker/develop/app.py .`?**
   - Để tận dụng **Docker layer cache**. `requirements.txt` ít thay đổi hơn code trong `app.py`. Khi chỉ sửa `app.py`, layer `COPY requirements.txt` và layer nặng `RUN pip install --no-cache-dir -r requirements.txt` vẫn trúng cache và không phải cài lại toàn bộ thư viện. (Lưu ý: `--no-cache-dir` chỉ tắt cache tải wheel của `pip` để ảnh nhỏ hơn, không tắt Docker layer cache).
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**
   - `CMD` định nghĩa lệnh hoặc tham số mặc định, có thể bị ghi đè hoàn toàn nếu truyền lệnh mới lúc `docker run <image> <cmd>`.
   - `ENTRYPOINT` cố định chương trình chính chạy khi container khởi động; các đối số truyền thêm lúc `docker run` (hoặc `CMD` đi kèm) sẽ được nối làm tham số cho `ENTRYPOINT`.

### Exercise 2.2: Build và chạy bản `develop`

- Lệnh build từ gốc repo:
  ```bash
  docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
  docker run --rm -p 8000:8000 -d --name agent-dev my-agent:develop
  curl -i -X POST "http://localhost:8000/ask?question=What+is+Docker"
  docker images my-agent:develop
  docker stop agent-dev
  ```
- **Kết quả đo thực tế (WSL2 `Ubuntu-24.04` + Docker CE `29.10.1`):**

```http
$ docker images my-agent:develop
REPOSITORY:TAG      SIZE
my-agent:develop    1.67GB

# POST /ask?question=What+is+Docker
HTTP/1.1 200 OK
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 (`FROM python:3.11-slim AS builder`):** cài `gcc`, `libpq-dev` để biên dịch dependencies nếu cần, sau đó cài gói Python vào `/root/.local` bằng `pip install --no-cache-dir --user -r requirements.txt`.
- **Stage 2 (`FROM python:3.11-slim AS runtime`):** tạo user không phải root (`appuser`), chỉ copy thư mục `/root/.local` từ stage `builder` sang `/home/appuser/.local` cùng `main.py` và `utils/mock_llm.py`, thiết lập `PATH`, `PYTHONPATH`, `USER appuser`, `HEALTHCHECK` và `CMD`.
- **Vì sao image nhỏ hơn:** toàn bộ compiler (`gcc`), header (`libpq-dev`), cache apt và công cụ build ở Stage 1 bị loại bỏ hoàn toàn khỏi image cuối; bề mặt tấn công (attack surface) cũng giảm và app không chạy dưới quyền `root`.
- **So sánh kích thước đo thực tế (`docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .`):**
  - Develop (`my-agent:develop`): `1.67GB` (`1,667,796,728` bytes ≈ `1,590.5 MiB`)
  - Production (`my-agent:advanced`): `240MB` (`239,815,542` bytes ≈ `228.7 MiB`)
  - Chênh lệch: **giảm 85.62%** (nhỏ hơn ~6.95 lần, tiết kiệm ~1.43 GB).

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

**Sơ đồ kiến trúc các service (đọc từ `docker-compose.yml` và `nginx/nginx.conf`):**

```text
Client ──(:80 / :443)──▶ nginx (nginx:alpine, reverse proxy + rate limit 10r/s)
                             │
                             ▼ (mạng internal, port 8000)
                           agent (FastAPI, target: runtime)
                             ├──▶ redis (redis:7-alpine, port 6379, volume redis_data)
                             └──▶ qdrant (qdrant/qdrant:v1.9.0, port 6333, volume qdrant_data)
```

- Các service giao tiếp nội bộ qua Docker bridge network `internal` bằng tên service (`redis://redis:6379/0`, `http://qdrant:6333`). Chỉ `nginx` mở port `80`/`443` ra ngoài host; `agent` chờ `redis` và `qdrant` đạt `condition: service_healthy` mới khởi động. Đã tạo sẵn file `.env.local` (nằm trong `.gitignore`).
- **Kết quả test thực tế qua Nginx (`docker compose -f 02-docker/production/docker-compose.yml up -d --build`):**

```http
# GET http://127.0.0.1/health
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":1.0,"version":"2.0.0","timestamp":"2026-11-25T15:34:41.939059"}

# POST http://127.0.0.1/ask
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1: Deploy agent Part 6 lên Railway (nền tảng chính)

- **URL Public (agent Part 6):** https://agent-production-f110c215.up.railway.app (chi tiết lệnh deploy và biến môi trường trong [DEPLOYMENT.md](DEPLOYMENT.md))
- **Cách deploy:** dùng Railway CLI trong thư mục `06-lab-complete/`: `railway init` → `railway add --database redis` → `railway add --service agent --variables ...` (đặt `AGENT_API_KEY`, `REDIS_URL=${{Redis.REDIS_URL}}`, `ENVIRONMENT`, `LOG_LEVEL`, rate limit, budget trên Railway) → `railway up --service agent` (build theo `Dockerfile` + `railway.toml`) → `railway domain`.
- **Kết quả 4 lệnh CP6 trên URL public (2026-11-25 23:25 GMT+7):**

```text
GET  /health                   → 200 {"status":"ok","environment":"production"}
GET  /ready                    → 200 {"status":"ready"}
POST /ask (không X-API-Key)    → 401 {"detail":"Invalid or missing X-API-Key"}
POST /ask (có X-API-Key)       → 200 {"question":"Hello","answer":"Agent đang hoạt động tốt! ...","usage":{...}}
12 request /ask tiếp theo      → 200 ×9, sau đó 429 ×3 (vượt 10 req/phút)
```

- **Ảnh chụp deploy:** [screenshots/dashboard.png](screenshots/dashboard.png) (dashboard Railway), [screenshots/running.png](screenshots/running.png) (`railway status`/`service list`: agent + Redis Online, log JSON, `/health` + `/ready` 200), [screenshots/test.png](screenshots/test.png) (4 lệnh CP6 + 429).
- **Thu hoạch:** Railway inject `PORT=8080` nên Dockerfile phải chạy `--port ${PORT:-8000}` thay vì cố định 8000; Redis được nối qua private network (`redis.railway.internal`), không mở ra Internet.

### Exercise 3.2: Nền tảng còn lại (Render)

Không deploy thêm lên Render; thay vào đó so sánh `railway.toml` và `render.yaml` bên dưới (theo RUBRIC, mục "Nền tảng còn lại").

### So sánh `railway.toml` và `render.yaml` (Exercise 3.1 vs 3.2)

| Tiêu chí | `railway.toml` | `render.yaml` |
| --- | --- | --- |
| **Định dạng & phạm vi** | TOML (`[build]`, `[deploy]`), cấu hình cho **một service** ứng dụng | YAML Blueprint, mô tả **Infrastructure as Code cho nhiều service** trong cùng 1 file (web + managed Redis) |
| **Cách build** | `builder = "DOCKERFILE"` (hoặc `NIXPACKS`) | `runtime: docker` (hoặc `runtime: python` kèm `buildCommand`/`startCommand`) |
| **Health check** | `healthcheckPath = "/health"`, `healthcheckTimeout = 30` | `healthCheckPath: /health` |
| **Biến môi trường & secret** | Không khai báo Redis/env trong file `railway.toml`; tạo Redis add-on và đặt `AGENT_API_KEY`, `REDIS_URL` qua Railway CLI hoặc Dashboard | Khai báo trực tiếp `envVars` trong YAML: secret dùng `generateValue: true` hoặc `sync: false`, `REDIS_URL` tham chiếu từ service Redis (`fromService`) |
| **Chính sách restart / region** | `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3` | Khai báo `plan: free`, `region: singapore`, `autoDeploy: true` |

### Exercise 3.3: Mô tả pipeline CI/CD Cloud Run (`03-cloud-deployment/production-cloud-run/`)

Pipeline trong `cloudbuild.yaml` gồm 4 bước tuần tự khi push lên nhánh `main`: (1) chạy unit test bằng `pytest` trong container `python:3.11-slim`; (2) build Docker image gắn tag `$COMMIT_SHA` và `latest` (tận dụng `--cache-from`); (3) push các tag lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`); (4) chạy `gcloud run deploy` lên region `asia-southeast1` với `min-instances=1` (tránh cold start), `max-instances=10`, giới hạn `512Mi`/`1 CPU` và inject secret từ Secret Manager. File `service.yaml` định nghĩa cấu hình declarative chuẩn Knative tương ứng, bổ sung `containerConcurrency: 80`, `livenessProbe` (`/health`) và `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

Chạy với `AGENT_API_KEY=secret-key-123`:

```http
# 1) Không có X-API-Key → 401
HTTP/1.1 401 Unauthorized
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# 2) Có header X-API-Key: secret-key-123 → 200
HTTP/1.1 200 OK
content-length: 122
content-type: application/json

{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2 & 4.3: JWT + Rate Limiting (`04-api-gateway/production/app.py`)

Lấy token qua `POST /auth/token` với `{"username":"student","password":"demo123"}` (`role="user"`, giới hạn 10 req/phút). Giá trị token đã được che (`<JWT_TOKEN_REDACTED>`):

```http
# 1) Thiếu Authorization header → 401
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# 2) Có Bearer token hợp lệ (request 1) → 200
HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY

{"question":"what is docker?","answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}

# 3) Vòng lặp spam sang request thứ 11 trong cùng 60s → 429
Request 2: 200
Request 3: 200
Request 4: 200
Request 5: 200
Request 6: 200
Request 7: 200
Request 8: 200
Request 9: 200
Request 10: 200
Request 11: 429 Too Many Requests
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795618186
retry-after: 56
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":56}}
```

- **Thuật toán dùng trong `rate_limiter.py`:** Sliding Window Counter dùng `collections.deque` lưu timestamp theo từng `user_id`; mỗi lần check sẽ `popleft()` các timestamp cũ hơn `now - 60s`, nếu `len(window) >= max_requests` thì trả `429` kèm `Retry-After`.
- **Giới hạn & phân quyền:** `rate_limiter_user` là `10` req/phút; `rate_limiter_admin` là `100` req/phút (chọn dựa theo `user["role"] == "admin"`, có thể bỏ qua bước check cho admin nếu muốn).

### Exercise 4.4: Cách làm Cost Guard

- Trong `04-api-gateway/production/cost_guard.py` (và bản Redis ở `06-lab-complete/app/cost_guard.py`), hệ thống kiểm tra ngân sách **trước khi gọi LLM** (`check_budget`): nếu chi tiêu hiện tại đã đạt hoặc vượt ngưỡng ngày/tháng thì chặn ngay bằng `HTTP 402 Payment Required`.
- **Sau khi LLM trả lời** (`record_cost`), chi phí thực tế được tính từ `input_tokens` và `output_tokens` nhân đơn giá theo 1K token (`PRICE_INPUT_PER_1K`, `PRICE_OUTPUT_PER_1K`), rồi cộng dồn nguyên tử vào Redis bằng `INCRBYFLOAT` kèm `EXPIRE` theo ngày/tháng.
- **Vì sao cần cả Rate Limit và Cost Guard:** Rate limit kiểm soát *tốc độ gọi* (req/phút) để chống spam/DoS, còn Cost guard kiểm soát *tổng tiền tiêu thụ* (USD/ngày hoặc tháng) vì một số ít request có prompt/output rất dài hoặc model đắt vẫn có thể làm cạn ngân sách dù không vượt rate limit.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health Check & Graceful Shutdown (`05-scaling-reliability/develop/app.py`)

Kết quả chạy thực tế bản `develop`:

```http
# GET /health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":1.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T14:48:49.448873+00:00","checks":{"memory":{"status":"ok","used_percent":84.9}}}

# GET /ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}

# POST /ask?question=hello
HTTP/1.1 200 OK
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

- **Khác biệt giữa `/health` (liveness) và `/ready` (readiness):**
  - `GET /health` kiểm tra process còn sống không; nếu fail, orchestrator/Docker sẽ **restart container**. Trong Part 6, `/health` phải luôn trả `200` kể cả khi Redis mất kết nối để tránh restart vòng lặp vô ích khi lỗi đến từ Redis ngoài.
  - `GET /ready` kiểm tra instance đã sẵn sàng phục vụ chưa (đã load xong, không đang shutdown, kết nối Redis OK). Nếu trả `503`, Load Balancer/Nginx ngừng gửi traffic mới tới instance đó nhưng **không restart** nó.
- **Graceful shutdown:** Khi nhận `SIGTERM`, app chuyển `_is_ready = False` (để LB ngừng gửi request mới), chờ các request đang chạy (`in-flight`) hoàn thành rồi mới đóng kết nối Redis và thoát với exit code `0`.

### Exercise 5.3–5.5: Stateless Design & Load Balancing (`05-scaling-reliability/production/`)

- **Vì sao state trong RAM hỏng khi scale:** Khi chạy `agent` với 3 instance sau Nginx round-robin, request 1 có thể vào Instance 1 (lưu history vào dict RAM của Instance 1), nhưng request 2 lại đi sang Instance 2 vốn không có dữ liệu đó → mất ngữ cảnh hội thoại.
- **Cách sửa trong `05-scaling-reliability/production/app.py`:** Lưu toàn bộ lịch sử phiên theo key `session:{session_id}` trong **Redis** (TTL 3600s, giữ tối đa 20 message), còn Nginx ở cổng `8080` phân phối tải round-robin sang các container `agent` và gắn header `X-Served-By` để quan sát instance phục vụ.
- **Kết quả chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `/opt/lab-venv/bin/python test_stateless.py` trong WSL2:**
  - `docker compose` đã khởi tạo đủ `k5-day14-scaling-agent-1`, `k5-day14-scaling-agent-2`, `k5-day14-scaling-agent-3`, `k5-day14-scaling-redis-1`, `k5-day14-scaling-nginx-1`.

```text
Session ID: 7db1be76-46d7-4a58-b777-fef41b852689
Total requests: 5
Instances used: {'instance-50c853'}
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

  - *Ghi chú quan sát:* Cả 10 tin nhắn (5 câu hỏi + 5 câu trả lời) đều được lưu và truy xuất nguyên vẹn từ Redis. Tuy nhiên `Instances used` chỉ hiện 1 instance (`instance-50c853`) do `05-scaling-reliability/production/nginx.conf` cấu hình `server agent:8000;` mà chưa bật `resolve` (Nginx cache một IP trả về lúc khởi động thay vì re-resolve DNS cho nhiều replica). Ở Part 7 (`benchmark-observability/production`), nhờ cấu hình `resolve`, header `X-Served-By` luân phiên qua các IP container khác nhau.

---

## Part 6: Final Project — Kết quả `check_production_ready.py`

Chạy `/opt/lab-venv/bin/python check_production_ready.py` đầy đủ (không skip) trong WSL2 `Ubuntu-24.04` với Docker CE `29.10.1`:

```text
  ⏳ Build Docker image prod-check:cd722b40 (Docker 29.10.1)
  ...
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)     [build 119s · 238 MB · GET /health → 200]
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)         [200 với Redis · 503 khi mất Redis]
     ✅ API Key authentication                  [thiếu/sai → 401 · đúng → 200]
     ✅ Rate limiting                           [429 sau 5 req · persist qua restart trong Redis]
     ✅ Cost guard                              [402 ở request thứ 1 khi budget ≈ 0]
     ✅ Config từ environment variables
     ✅ Structured logging                      [17 dòng JSON hợp lệ]
     ✅ Graceful shutdown                       [SIGTERM exit code 0 · docker stop exit code 0, 1.3s]
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

---

## AI Log

| Thời điểm | Yêu cầu / Nội dung hỏi AI | Kết quả nhận được | Tự chỉnh sửa & kiểm tra thực tế |
| --- | --- | --- | --- |
| Day 14 Lab | Đọc toàn bộ tài liệu `.md`, phân tích yêu cầu và thiết kế code cho các file `TODO` trong `06-lab-complete/` | Triển khai `config.py`, `redis_client.py`, `auth.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml` | Phát hiện và sửa lỗi quyền non-root trong `06-lab-complete/Dockerfile` (`COPY --chown=appuser:appuser` + `exec python -m uvicorn` để nhận `SIGTERM` đúng PID 1), sau đó chạy `/opt/lab-venv/bin/python check_production_ready.py` trong WSL2 `Ubuntu-24.04` đạt **`PASS 12/12 · 43/43 checks passed`**. |
| Day 14 Lab | Chạy kiểm chứng Docker Part 2, Part 5 và toàn bộ benchmark/observability Part 7 (Bước 1 & Bước 2) | Thu thập kích thước image `my-agent:develop` vs `my-agent:advanced`, output Compose/Nginx/Redis stateless, 10 file JSON (`reports/`), CSV Locust `scale_1` / `scale_3`, screenshot Grafana/Jaeger/Prometheus | Tự phát hiện lỗi `ModuleNotFoundError: No module named 'uvicorn'` ở `06-lab-complete/benchmark-observability/production/Dockerfile` do thiếu `PYTHONUSERBASE=/home/agent/.local` & `--chown=agent:agent`; bổ sung `KNOWLEDGE_BASE` và metric `agent_question_length_chars`, đạt `23/23 (100.0%)` trên golden dataset và xác minh `promtool test rules`. |
| Day 14 Lab | Rà soát bài theo `SUBMISSION.md`/`RUBRIC.md`, deploy agent Part 6 lên Railway bằng Railway CLI | Tạo project `day14-production-agent` (agent + Redis), đặt biến môi trường trên Railway, script test CP6 và cập nhật `DEPLOYMENT.md`, Part 3 | Tự đăng nhập Railway; kiểm chứng URL public trả `/health` 200, `/ready` 200, `/ask` 401 / 200 / 429 và `check_production_ready.py --public-url` báo `✅ Public URL ... → 200`; tự chụp `screenshots/dashboard.png` trên dashboard Railway. |
