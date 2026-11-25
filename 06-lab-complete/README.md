# Part 6 — Final Project: Production-ready AI Agent

Agent đã được hoàn thiện từ bản khung Part 6, kết hợp cấu hình môi trường, API key, Redis rate limit/cost guard, JSON logging và graceful shutdown.

**CP5: `PASS 12/12`, 43/43 checks passed** khi chạy nguyên bản script chấm trong Ubuntu WSL2 có Docker. Bằng chứng: [output bản đầy đủ](../reports/cp5-production-ready.txt), [metadata kiểm tra](../reports/cp5-runtime.json), [kiểm tra đồng thời và Compose](../reports/cp5-probes.json).

Public URL được triển khai ở CP6. Tiêu chí "Public URL ready" của CP5 xác nhận cấu hình nền tảng và port, chưa thay thế việc kiểm tra URL cloud.

Bài chỉ được tính hoàn thành khi script chấm báo **`PASS 12/12`**:

```bash
pip install -r requirements.txt
python check_production_ready.py
```

---

## Checklist Deliverable

- [x] Dockerfile (multi-stage, < 500 MB)
- [x] docker-compose.yml (agent + redis)
- [x] .dockerignore
- [x] Health check endpoint (`GET /health`)
- [x] Readiness endpoint (`GET /ready`)
- [x] API Key authentication
- [x] Rate limiting
- [x] Cost guard
- [x] Config từ environment variables
- [x] Structured logging
- [x] Graceful shutdown
- [x] Public URL ready (Railway / Render config)

---

## Script chấm dựa vào những tiêu chí dưới đây

Script tự khởi động agent của bạn, gọi API thật, build và chạy Docker image. Để chấm được, agent phải tuân theo các quy ước sau:

| Hạng mục | Yêu cầu |
|----------|---------|
| Điểm vào | `app/main.py` có biến `app` (FastAPI), chạy được bằng `uvicorn app.main:app --workers 2` từ thư mục này |
| `GET /health` | Luôn trả **200** khi process còn chạy, kể cả khi Redis chưa kết nối được |
| `GET /ready` | **200** khi sẵn sàng; **503** khi Redis (`REDIS_URL`) không kết nối được |
| `POST /ask` | Body JSON `{"question": "..."}` (được phép có thêm `user_id`) → **200** |
| API key | Header `X-API-Key` phải trùng biến `AGENT_API_KEY`; thiếu hoặc sai → **401** |
| Rate limit | Tối đa `RATE_LIMIT_PER_MINUTE` request / 60 giây cho mỗi API key; vượt → **429** (nên có header `Retry-After`). State lưu trong **Redis**, vẫn còn sau khi restart agent |
| Cost guard | Tổng chi phí vượt `DAILY_BUDGET_USD` (hoặc `MONTHLY_BUDGET_USD`) → **402** |
| Biến môi trường | Đọc từ env: `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD` / `MONTHLY_BUDGET_USD`, `PORT`, `ENVIRONMENT`. Liệt kê đủ trong `.env.example`. Script chạy với `ENVIRONMENT=staging` |
| Log | Mỗi dòng log của app là **1 JSON object hợp lệ** (log của uvicorn không tính) |
| Graceful shutdown | Nhận SIGTERM khi đang có request → request đó vẫn trả 200, process tự thoát với exit code 0. Trong Docker, `docker stop` phải xong trong < 10 giây |
| Docker image | Multi-stage, base slim, user non-root, có `HEALTHCHECK`, < 500 MB. `CMD` lắng nghe theo biến `PORT` (mặc định 8000), uvicorn là PID 1. Container khởi động được khi **không có** Redis |
| Compose | Một service build từ `Dockerfile` + một service dùng image `redis:*`; agent có `REDIS_URL` trỏ tới service Redis và `depends_on` nó |
| `.dockerignore` | Loại trừ `.env`, `__pycache__`, `venv` |
| Deploy config | `railway.toml` (builder `DOCKERFILE`, `healthcheckPath = "/health"`) **hoặc** `render.yaml` (`type: web`, `healthCheckPath: /health`, secret dùng `generateValue` / `sync: false`) |

---

## Cấu trúc và trách nhiệm

```
06-lab-complete/
├── app/
│   ├── main.py           # API, validation, JSON logging và lifespan cleanup
│   ├── config.py         # Cấu hình env, nạp .env với env hiện có được ưu tiên
│   ├── auth.py           # Thiếu/sai X-API-Key → 401
│   ├── rate_limiter.py   # Redis sorted set + Lua atomic, vượt quota → 429
│   ├── cost_guard.py     # Giữ chỗ/đối soát budget UTC trong Redis → 402
│   └── redis_client.py   # Client lazy, timeout 1 giây, không fallback RAM
├── utils/mock_llm.py     # Mock LLM — có sẵn, không cần sửa
├── Dockerfile            # Multi-stage venv, non-root, 2 worker, PID 1 Uvicorn
├── docker-compose.yml    # Agent + Redis AOF, named volume, noeviction
├── .dockerignore         # Secrets, cache, venv và Part 7 không vào image
├── .env.example          # Mẫu đầy đủ, key để trống
├── railway.toml          # Railway dùng thư mục service này làm root
├── render.yaml           # Blueprint web + Key Value, secret tự sinh
├── requirements.txt      # Có sẵn
├── check_production_ready.py   # Script chấm — không sửa
└── benchmark-observability/    # Part 7 — làm sau khi xong Part 6
```

**Thứ tự đọc code:** `config.py` → `redis_client.py` → `auth.py` → `rate_limiter.py` → `cost_guard.py` → `main.py` → Dockerfile/Compose/deploy config. Phần giải thích và kết quả nằm trong [MISSION_ANSWERS.md](../MISSION_ANSWERS.md).

---

## Chạy local

```bash
# Từ gốc repo, script setup tạo .env với key ngẫu nhiên nếu chưa có:
bash scripts/setup-wsl.sh
source .venv/core/bin/activate
cd 06-lab-complete

# Bật agent + Redis; Compose đọc .env, nhưng dùng Redis nội bộ:
docker compose -p k5-day14-final up -d --build --wait

# Chỉ export key/port vào terminal local, không in hoặc chép key vào báo cáo:
set -a; source .env; set +a
curl -i "http://localhost:${PORT:-8000}/health"
curl -i "http://localhost:${PORT:-8000}/ready"
curl -i -X POST "http://localhost:${PORT:-8000}/ask" \
  -H "X-API-Key: $AGENT_API_KEY" -H 'Content-Type: application/json' \
  -d '{"question":"What is deployment?"}'

docker compose -p k5-day14-final down
```

Nếu chỉ chạy Python, cần Redis riêng tại `REDIS_URL`; app vẫn khởi động khi Redis chưa có, nhưng `/ready` và `/ask` sẽ trả 503. Dùng `uvicorn app.main:app --workers 2 --env-file .env` từ thư mục này, với virtualenv đã kích hoạt. Không nạp `.env` vào shell trước khi chạy script chấm đầy đủ nếu muốn script tự tạo Redis tạm; hoặc truyền `--redis-url` tới Redis thử đang hoạt động.

Budget trong lab là chi phí mô phỏng của mock, không phát sinh gọi API LLM thật. Ledger dùng đơn vị nguyên 10⁻⁹ USD, theo ngày UTC và environment. Mỗi request giữ chỗ chi phí của câu trả lời mock dài nhất rồi hoàn phần thừa sau response; các worker dùng chung ledger. Nếu process chết sau khi giữ chỗ, phần đó được giữ tới hết kỳ để tránh mở lại ngân sách không chắc chắn.

---

## Chấm bài

```bash
python check_production_ready.py                 # chấm đầy đủ — cần Docker đang chạy
python check_production_ready.py --skip-docker   # chế độ nhanh khi đang làm (bỏ build image)
python check_production_ready.py --static-only   # chỉ đọc file, không chạy agent
python check_production_ready.py --public-url https://your-app.railway.app   # thêm kiểm tra URL đã deploy
```

- Kết quả in theo từng tiêu chí: ✅ đạt · ❌ chưa đạt · ⚠️ chưa kiểm tra được.
- **Chỉ PASS khi cả 12 tiêu chí ✅.** Mục ⚠️ (vd máy chưa bật Docker) cũng tính là chưa đạt, nên khi nộp bài phải chạy chế độ đầy đủ.
- Lần đầu chạy, script build Docker image nên mất vài phút. Bài test stateless cần Redis: script dùng `REDIS_URL` nếu có, không thì tự bật container `redis:7-alpine` tạm thời.

---

## Deploy

**Railway**

```bash
npm i -g @railway/cli
railway login
railway init
railway variables set AGENT_API_KEY=your-secret-key
railway up
railway domain        # nhận public URL
```

**Render:** push source đã hoàn thiện → tạo Blueprint từ `06-lab-complete/render.yaml`. Web dùng `rootDir: 06-lab-complete`, Key Value cùng Blueprint cấp `REDIS_URL`, `AGENT_API_KEY` được sinh trên nền tảng. Blueprint chỉ định `plan: free` cho hai service; Key Value free không lưu bền dữ liệu qua việc thay/restart datastore. Các field được đối chiếu theo [Render Blueprint specification](https://render.com/docs/blueprint-spec).

Sau khi deploy: `python check_production_ready.py --public-url <URL>` và ghi URL vào `DEPLOYMENT.md` (xem [DAY14_DELIVERY_CHECKLIST.md](../DAY14_DELIVERY_CHECKLIST.md)).

---

## Part 7 — Benchmark & Observability

Agent đã chạy được, bước tiếp theo là đo xem nó **nhanh** và **đúng** tới đâu, rồi **giám sát** khi chạy thật:

```bash
cd benchmark-observability
```

| Thư mục | Nội dung |
|---------|----------|
| `develop/` | Agent có `/metrics`, load test (p50/p95/p99, SLO), eval trên golden dataset + quality gate |
| `production/` | Docker Compose: agent x2 + Nginx + Prometheus + Grafana + Jaeger + Locust, 4 alert rules |

Hướng dẫn đầy đủ: [benchmark-observability/README.md](benchmark-observability/README.md). Nộp kèm `BENCHMARK_REPORT.md` theo [mẫu](benchmark-observability/BENCHMARK_REPORT_TEMPLATE.md).
