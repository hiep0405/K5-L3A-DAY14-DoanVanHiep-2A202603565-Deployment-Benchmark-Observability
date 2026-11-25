# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây (Mục 2, Mục 3, Mục 4, Mục 5) được đo trực tiếp từ lệnh chạy trên máy và khớp 100% với các file trong `reports/`, `benchmark-results/` và 4 screenshot Part 7 trong `screenshots/`.

**Họ tên:** Đoàn Văn Hiệp (`2A202603565`, lớp `K5-L3A`)
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11, Intel Core i5-12450HX (8 cores / 12 threads), 19.8 GB RAM + WSL2 (`Ubuntu-24.04`) + Docker CE `29.10.1` + Python `3.12`

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `< 500 ms` | Request bình thường của agent v2 tốn ~140–230ms (retrieval + mock LLM); ngưỡng 500ms giữ trải nghiệm chat phản hồi nhanh cho 95% lượt gọi nhưng không quá chặt với jitter bình thường. |
| Error rate `/ask` | `< 2.0 %` | Mock LLM có lỗi upstream ngẫu nhiên mặc định `1%` (`MOCK_ERROR_RATE=0.01`), đặt error budget `2%` để hấp thụ dao động nhỏ nhưng phát hiện được khi lỗi tăng bất thường. |
| Accuracy trên golden dataset | `>= 85 %` (mục tiêu sau sửa KB: `100 %`) | Đảm bảo agent v2 với RAG trả lời đúng tối thiểu 85% câu hỏi cốt lõi và không bị regression so với phiên bản trước trước khi merge/deploy. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Chạy `python load_test.py --url http://127.0.0.1:8002 --requests 300 --concurrency <c>` (cấu hình mặc định `MOCK_SLOW_RATE=0.03`, `MOCK_ERROR_RATE=0.01`, SLO `p95 <= 500ms`, `error_rate <= 2.0%`):

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.95 | 201.5 | 235.0 | 1711.5 | 0.00% | PASS |
| 10 | 34.02 | 199.5 | 525.4 | 1707.2 | 1.00% | FAIL |
| 50 | 107.58 | 203.4 | 250.0 | 1737.9 | 0.67% | PASS |
| 100 | 46.62 | 432.9 | 4126.6 | 4606.4 | 1.00% | FAIL |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

Không. Từ concurrency `1` lên `10` và `50`, RPS tăng mạnh (`3.95` → `34.02` → `107.58` req/s) nhờ event loop xử lý bất đồng bộ nhiều `asyncio.sleep` song song. Tuy nhiên lên tới `concurrency=100` trên 1 worker đơn lẻ, hệ thống chạm điểm bão hòa (event loop scheduling + socket contention trên Windows), khiến throughput sụt xuống còn `46.62` req/s, `p50` tăng hơn gấp đôi (`432.9` ms) và `p95` vọt lên `4126.6` ms. Ở `c=10`, tỷ lệ slow ngẫu nhiên 3% rơi nhỉnh hơn 5% trong mẫu 300 request nên `p95` đạt `525.4` ms và chạm ngưỡng `FAIL`.

### 2.2 Tail latency

Chạy `--requests 300 --concurrency 20` khi thay đổi `MOCK_SLOW_RATE`:

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 195.0 | 231.8 | 241.8 |
| 0.03 (mặc định) | 240.6 | 237.7 | 1696.0 |
| 0.1 | 328.4 | 1699.4 | 1715.0 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

`p99` và `p95` nhạy nhất với request chậm (tail latency): khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03`, `avg` chỉ tăng `45.6 ms` (`195.0` → `240.6` ms) nhưng `p99` nhảy vọt ~7 lần lên `1696.0` ms. Khi `MOCK_SLOW_RATE=0.1` (> 5% số request bị chậm), cả `p95` cũng nhảy lên `1699.4` ms trong khi `avg` mới là `328.4` ms. Nếu đặt SLO theo `average`, phần lớn request nhanh sẽ che giấu trải nghiệm rất tệ của 1–10% người dùng ở phần đuôi phân bố.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Chạy với `MOCK_ERROR_RATE=0` trên 23 câu hỏi trong `eval/golden_dataset.jsonl`:

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 56.3 | 109.1 | 113.7 |
| Tổng cost (USD) | $0.000394 | $0.000762 | $0.000790 |
| Cost / câu đúng (USD) | $0.00039375 | $0.00003627 | $0.00003436 |
| Quality gate | FAIL (min 80%) | PASS (baseline v1, 0 regression) | PASS (min 100%, baseline v2, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Bổ sung entry từ khóa `["jwt"]` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` và `production/utils/mock_llm.py` giải thích JWT chứa chữ ký số, thông tin user và thời điểm hết hạn. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Bổ sung entry từ khóa `["hpa", "kubernetes", "autoscal"]` vào `KNOWLEDGE_BASE` giải thích Kubernetes HPA scale pod dựa trên CPU, memory hoặc custom metrics. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- Agent `v2` có thêm bước retrieval nên `avg tokens / câu` tăng gần gấp đôi (`56.3` → `109.1` → `113.7` tokens) và `p95` latency tăng nhẹ (`202.2` ms → `219.4` ms).
- Bù lại, độ chính xác tăng từ `4.3%` lên `91.3%` (và `100.0%` sau khi bổ sung KB). Nếu xét trên **cost / câu trả lời đúng**, `v2` sau khi sửa KB chỉ tốn `$0.00003436` — rẻ hơn **~11.5 lần** so với `v1` (`$0.00039375`), vì `v1` tốn tiền cho 22/23 câu trả lời sai.
- **Quality gate trong CI:** Đã tạo file `.github/workflows/eval.yml` chạy `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85`. Khi kiểm chứng chạy `v1` với `--baseline reports/eval_v2.json --min-accuracy 0.85`, script in `❌ FAIL` và trả về **exit code `1`**, giúp GitHub Actions chặn merge PR nếu accuracy thấp hơn ngưỡng hoặc có bất kỳ câu nào bị regression.

### Kết quả bổ sung Exercise 7.1 (`/metrics` và cardinality)

Đã thêm Histogram `agent_question_length_chars` vào `06-lab-complete/benchmark-observability/develop/app.py`. Output thực tế từ `GET /metrics`:
- **Counter:** `http_requests_total{method="POST",route="/ask",status="200"} 1.0`, `llm_tokens_total{model="mock-llm-small",type="input"} 91.0`
- **Gauge:** `agent_in_flight_requests 0.0`, `agent_info{model="mock-llm-small",version="v2"} 1.0`
- **Histogram:** `http_request_duration_seconds_bucket{le="0.3",method="POST",route="/ask"} 1.0`, `agent_question_length_chars_bucket{le="50.0"} 1.0`
- **Vì sao dùng `route.path` thay vì `request.url.path`:** Nếu dùng URL thật khi bot quét hàng nghìn đường dẫn lạ (`/wp-admin`, `/.env`, `/a1b2c3`...), mỗi URL sinh thêm nhiều time series (theo từng `method`/`status` và các bucket histogram), gây **bùng nổ cardinality** và làm Prometheus cạn RAM.

---

## 4. Observability stack (production)

> Đã chạy full Docker Compose stack (`docker compose -p k5-day14-observability up -d --build`) trên WSL2 `Ubuntu-24.04` + Docker CE `29.10.1` (`agent` scale 2–3 replica, `nginx`, `prometheus`, `grafana`, `jaeger`, `locust`). Unit test alert rules (`promtool test rules`) đạt `SUCCESS`.

### 4.1 Screenshot & Bằng chứng `/metrics` + PromQL trực tiếp

- [x] Dashboard Grafana khi đang có tải (`screenshots/grafana-dashboard.png` — ghi nhận `Traffic: 17.7 req/s`, `Error rate: 0.42%`, `Latency p95: 289.23 ms`, `Saturation: 4`, `Instances: 3`, `LLM cost: $0.5523`)
- [x] Một trace chậm trong Jaeger (`screenshots/jaeger-slow-trace.png`)
- [x] Một trace lỗi trong Jaeger (`screenshots/jaeger-error-trace.png`)
- [x] Trang Alerts của Prometheus với ≥ 2 alert đang **firing** (`screenshots/prometheus-alert-firing.png` — 3 alert cùng `FIRING`: `LLMCostBurnRateHigh`, `AgentHighErrorRate`, `AgentHighLatencyP95`)

**Kết quả truy vấn PromQL (Exercise 7.4) dưới tải Locust 30 users:**
- Latency `p95` (`/ask`): `0.2907 s` (~`290.7 ms`), Latency `avg`: `0.2233 s` (~`223.3 ms`).
- RPS theo instance: `172.18.0.2:8000` → `9.45 req/s`, `172.18.0.3:8000` → `9.38 req/s` (cân bằng đều qua Nginx; header `X-Served-By` luân phiên giữa các IP container).
- Tokens/s theo loại: `input` = `1444.4 tok/s`, `output` = `753.0 tok/s`.
- Cost burn rate quy đổi: `$1.6756 / giờ`.
- Truy cập `GET http://127.0.0.1:8080/metrics` qua Nginx trả `404 Not Found` (được Nginx chặn công khai).

**Giải thích PromQL của dashboard & 4 alert rules (`alert_rules.yml` + `agent-overview.json`):**
- **Traffic & Error rate:** `sum(rate(http_requests_total{job="agent", route="/ask"}[1m]))` đo RPS; alert `AgentHighErrorRate` bắn khi tỷ lệ `status=~"5.."` trên tổng `/ask` vượt `5%` (`> 0.05`) liên tục trong `for: 1m`.
- **Latency p95:** `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{job="agent", route="/ask"}[1m])))` tính phân vị 95 từ các bucket; alert `AgentHighLatencyP95` bắn khi `p95 > 1s` liên tục `for: 2m`.
- **Availability:** `up{job="agent"} == 0` với `for: 30s` kích hoạt `AgentInstanceDown` khi Prometheus không scrape được `/metrics` (khi dùng `docker pause`, target vẫn nằm trong DNS nên `up == 0`).
- **Cost burn rate:** `sum(rate(llm_cost_usd_total{job="agent"}[5m])) * 3600 > 2` (với `for: 2m`) kích hoạt `LLMCostBurnRateHigh` khi tốc độ chi tiêu quy đổi vượt `$2/giờ`.

### 4.2 Thí nghiệm "phá hệ thống"

Chạy tải nền Locust 30 users (`-r 5`) rồi áp dụng từng thay đổi trên stack Docker Compose:

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`) | `88.2 giây` | `Error rate`, `Requests/s theo status code`, `LLM calls theo kết quả` |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`) | `145.5 giây` | `Latency p95`, `Latency /ask — p50 / p95 / p99` |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`) | `145.5 giây` (UI ghi nhận `$11.77/giờ`) | `Cost burn rate (USD/giờ)`, `LLM cost (1h)`, `LLM latency p95 theo model` |
| D | `docker pause` 1 instance | `AgentInstanceDown` (`for: 30s`) | `31.4 giây` (`sum(up{job="agent"})` giảm `2 → 1`) | `Instances up`, `Requests/s theo instance` |
| E | `AGENT_VERSION=v1` | Không có alert mới nào firing | N/A (`agent_info{version="v1"} = 2`) | `Retrieval hit ratio (agent v2)`, `Tokens/s`, `Phiên bản đang chạy` |

*(Ghi chú: trong lúc test nối tiếp E ngay sau A+B+C, cửa sổ `rate(...[5m])` của `LLMCostBurnRateHigh` từ đợt C chưa trôi hết nên cần đợi hết 5 phút để tự resolve; với bản `v1` thuần túy không có bất kỳ rule nào chuyển firing).*

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Các alert hạ tầng trong `alert_rules.yml` chỉ theo dõi lỗi HTTP 5xx, latency, availability (`up == 0`) và tốc độ chi phí — khi đổi sang `v1` (tắt retrieval), dịch vụ vẫn trả HTTP 200 nhanh và rẻ hơn nên toàn bộ bảng Golden Signals vẫn xanh. Để phát hiện sự cố chất lượng này cần:
1. Chạy **eval tự động trên golden dataset** trong CI/CD (quality gate `run_eval.py`) trước khi deploy bản mới.
2. Giám sát **metric đặc thù của pipeline RAG** như `agent_retrieval_total` (trong `agent-overview.json`: `Retrieval hit ratio`), độ dài câu trả lời hoặc điểm đánh giá LLM-as-judge / phản hồi người dùng (thumbs up/down) trên traffic production.

**Giải thích thêm cho Exercise 7.4 & 7.6 (từ cấu hình `nginx.conf` và `agent-overview.json`):**
- **Vì sao input tokens/s lớn hơn output tokens/s:** Với agent v2, input prompt gửi cho LLM bao gồm `SYSTEM_PROMPT` + tài liệu retrieve từ `KNOWLEDGE_BASE` + câu hỏi, trong khi output chỉ là câu trả lời ngắn gọn (đo thực tế trên Prometheus: `1444.4` input tokens/s so với `753.0` output tokens/s — gấp ~1.92 lần).
- **Vì sao `curl http://localhost:8080/metrics` trả 404:** Trong `production/nginx/nginx.conf` (dòng 22–24), `location = /metrics { return 404; }` chặn truy cập từ bên ngoài để không lộ thông tin nội bộ hệ thống; chỉ Prometheus trong mạng Docker `obs_net` mới scrape trực tiếp `agent:8000/metrics`.
- **Vì sao lỗi 504 ở Nginx (khi pause container) không hiện trên Error rate của agent:** Lỗi 504 do Nginx tự ngắt khi chờ quá `proxy_read_timeout 10s`; request không được agent xử lý xong nên counter `http_requests_total` bên trong agent không tăng.

### 4.3 Debug bằng trace

Dữ liệu thật thu từ Docker Compose stack (Jaeger UI + `docker compose logs agent`):

- **Request chậm tìm được (`screenshots/jaeger-slow-trace.png`):**
  - `trace_id`: `4c2e24895e50029f4ec38d61aff48683` (`span_id`: `dab2c77a5afd4b77`, instance `c2ee9abc9f8e` / `172.18.0.2:8000`)
  - **Bóc tách trên Jaeger UI (`Duration: 1.7s`, `Total Spans: 4`, `Depth: 3`):**
    - `POST /ask` (`200`): `1.7s`
    - `agent.run` (`agent.version = v2`, `agent.question.length = 51`): `1.7s`
    - `agent.retrieve_context`: `24.5 ms`
    - `chat mock-llm-small`: **`1691.9 ms`** (chiếm ~99% tổng thời gian — bottleneck nằm ở bước gọi LLM, không phải retrieval)
  - Dòng log JSON tương ứng:

```json
{"ts": "2026-11-25T15:56:48.677937+00:00", "level": "INFO", "service": "observable-agent", "instance": "c2ee9abc9f8e", "event": "llm_call", "trace_id": "4c2e24895e50029f4ec38d61aff48683", "span_id": "dab2c77a5afd4b77", "request_id": "5f2bcc19779a", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 73, "output_tokens": 35, "cost_usd": 3.2e-05, "llm_ms": 1691.9}
```

- **Request lỗi (`503`) tìm được (`screenshots/jaeger-error-trace.png`):**
  - `trace_id`: `788d897e36d4e7b84331a3333ca40fbe` (`span_id`: `2ea1073300c91b7d`, instance `9f290f8d30c1` / `172.18.0.3:8000`)
  - **Bóc tách trên Jaeger UI (`Duration: 98.2 ms`, `Total Spans: 4`, HTTP `503`):**
    - `POST /ask` (`503`): `98.2 ms`
    - `agent.run` (`96.8 ms`): gắn event `exception` (`exception.message = Upstream LLM error: 503 Service Unavailable (mock)`)
    - `agent.retrieve_context`: `25.3 ms`
    - `chat mock-llm-small` (`71.1 ms`): đánh dấu lỗi (`!`) ở bước gọi LLM upstream
  - Dòng log JSON tương ứng:

```json
{"ts": "2026-11-25T15:56:46.233460+00:00", "level": "INFO", "service": "observable-agent", "instance": "9f290f8d30c1", "event": "llm_error", "trace_id": "788d897e36d4e7b84331a3333ca40fbe", "span_id": "2ea1073300c91b7d", "request_id": "788b453312a5", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu `POST /ask` từ `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv` (Locust `--headless -u 100 -r 10 -t 2m`):

| Số instance | RPS (`/ask` / Aggregated) | p50 (ms) | p95 (ms) | p99 (ms) | Failures (`/ask`) |
|---|---|---|---|---|---|
| 1 | 60.13 / 66.13 | 190 | 230 | 1700 | 69 / 7160 (0.96%) |
| 3 | 59.99 / 65.96 | 190 | 220 | 1700 | 77 / 7170 (1.07%) |

*(Tổng request cả `/ask` + `/health` theo dòng `Aggregated`: `7875` request với `scale=1`, `7884` request với `scale=3`).*

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

Scale từ 1 lên 3 instance chỉ giảm nhẹ `p95` từ `230 ms` xuống `220 ms`, còn RPS (`~60 req/s` cho `/ask`), `p50` (`190 ms`) và `p99` (`1700 ms`) gần như giữ nguyên vì hai nguyên nhân:
1. **Nút thắt nằm ở tốc độ phát tải của client Locust, chưa chạm ngưỡng CPU/event-loop của backend:** Trong `locust/locustfile.py`, mỗi trong 100 user có `wait_time = between(0.5, 2)` (nghỉ trung bình 1.25s giữa các request cộng ~0.21s phản hồi), nên 100 user chỉ tạo ra tổng lưu lượng ổn định ~`66 req/s` (`~60 req/s` cho `/ask`, `~6 req/s` cho `/health`). Với FastAPI async I/O (`await asyncio.sleep`), 1 container đơn lẻ đã dư sức xử lý mức ~60 req/s này.
2. **Đuôi phân bố `p99 = 1700 ms` đến từ độ trễ mô phỏng upstream LLM (`MOCK_SLOW_RATE=0.03`):** 3% request chậm tốn ~1.7s ở phía LLM bất kể Nginx chia tải cho 1 hay 3 replica. Lợi ích thực sự của `--scale 3` trong kịch bản này là giảm nhẹ áp lực hàng đợi ở mức `p95` (`230 → 220 ms`) và đảm bảo **High Availability** (nếu 1 container gặp sự cố/pause, 2 container còn lại vẫn phục vụ bình thường). Khi test trực tiếp qua Nginx đã xác minh header `X-Served-By` luân phiên qua các IP container khác nhau.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. Không thể đánh giá tốc độ bằng `average` latency: chỉ cần 3–10% request chậm đã đẩy `p95`/`p99` lên gấp nhiều lần trong khi trung bình chỉ nhích nhẹ.
  2. Benchmark hiệu năng (`load_test.py`) và benchmark chất lượng (`eval/run_eval.py`) giải quyết hai bài toán độc lập: hệ thống xanh về RPS/error rate vẫn có thể trả lời sai hàng loạt (như `v1` vs `v2`), nên cần quality gate theo `cost / câu đúng` và regression check.
  3. 3 trụ cột Metrics (Prometheus/Grafana) + Traces (OpenTelemetry/Jaeger) + JSON Logs (`trace_id`) phối hợp giúp đi từ triệu chứng tổng thể xuống đúng bước chậm hoặc lỗi cụ thể.
- Nếu đưa agent này lên production thật, sẽ thêm các metric / alert:
  1. Synthetic monitoring & Nginx 5xx/504 alert từ phía ngoài Load Balancer (bù đắp điểm mù khi request không tới được agent).
  2. Alert khi `agent_retrieval_total{result="miss"}` tăng vọt hoặc `agent_info` đổi version bất thường, kết hợp đánh giá chất lượng mẫu (online eval / user feedback).
  3. Alert theo Redis latency / rate-limit `429` spike và budget consumption `402` để phát hiện sớm hành vi lạm dụng hoặc hết hạn mức.
