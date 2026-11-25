# Deployment Information

## Public URL

https://k5-l3a-truongvanthong-2a202603560-day14.onrender.com

## Platform

Render — Docker Web Service, Free, Singapore; Redis-compatible Render Key Value `day14-agent-cache` cùng region.

- Service ID: `srv-dc3afrjrjlhs73faoua0`.
- Deploy ID thành công trong ảnh người học cung cấp: `dep-dc3ahtnlk1mc73eds76g`.
- Source commit: `c17b3e2`, branch `main`.
- Dashboard hiển thị `Deploy succeeded | Live`, thời gian build/deploy 1 phút 9 giây, ngày 25/11/2026 lúc 16:23:02 GMT+7.
- Root Directory: `06-lab-complete`; Dockerfile Path: `./Dockerfile`; Docker context: `.`; Health Check Path: `/health`.

## Verification Status

Đã gọi URL public thật, đủ **4/4 phép thử PASS**. Kết quả đầy đủ trong [reports/cp6-runtime.json](reports/cp6-runtime.json); lần thử ban đầu không dùng key trong [reports/cp6-public-checks.json](reports/cp6-public-checks.json):

| Request | Mong đợi | Thực tế |
|---|---|---|
| `GET /health` | 200 | 200 |
| `GET /ready` | 200 | 200 |
| `POST /ask`, không có key | 401 | 401 |
| `POST /ask`, có key đúng | 200 | 200, có câu trả lời mock |

**CP6 đã triển khai thành công và đạt 4/4 phép thử API.** Kết quả kiểm tra cùng ba ảnh chụp được lưu trong repository.

## Test Commands

Trong Ubuntu, từ gốc repository:

```bash
.venv/core/bin/python scripts/verify-deployment.py
```

Script hỏi `Render AGENT_API_KEY (hidden):`. Copy key từ Environment của Web Service và dán vào terminal; ký tự không hiển thị khi nhập. Script chỉ gửi key tới URL HTTPS đã cấu hình, không lưu key trong báo cáo. Kết quả lưu ở `reports/cp6-runtime.json`, exit code 0 khi đủ 4/4 phép thử đạt.

Nếu không dán được vào ô nhập ẩn, chạy bằng Python Windows trong PowerShell:

```powershell
python scripts/verify-deployment.py --clipboard
```

Đợi script hỏi, chuyển sang Render để copy giá trị key, quay lại terminal rồi nhấn Enter, không dán. Script đọc bảng tạm vào bộ nhớ, không in hoặc lưu key.

Để chạy riêng các phép thử không cần key:

```bash
.venv/core/bin/python scripts/verify-deployment.py --public-only
```

### Health, readiness and authentication

```bash
BASE='https://k5-l3a-truongvanthong-2a202603560-day14.onrender.com'
read -rsp 'Render AGENT_API_KEY: ' AGENT_API_KEY; echo
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}'
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
unset AGENT_API_KEY
```

Expected statuses: `200`, `200`, `401`, `200`. Gói Free có thể cần chờ khởi động lại sau thời gian không có truy cập.

## Environment Variables

Các biến đã hướng dẫn nhập trên Render; không lưu giá trị secret trong repository:

- `REDIS_URL`: Internal Key Value URL của Redis cùng region.
- `AGENT_API_KEY`: tạo bằng Generate trên Render, đã hướng dẫn tạo lại sau khi key cũ hiện trong ảnh.
- `ENVIRONMENT`: `production`.
- `RATE_LIMIT_PER_MINUTE`: `10`.
- `DAILY_BUDGET_USD`: `1.0` (chi phí mock).
- `LOG_LEVEL`: `INFO`.
- `PORT`: Render cấp; app lắng nghe `0.0.0.0:$PORT`.

Không mở External Key Value để web service truy cập Redis; kết nối dùng mạng nội bộ. Redis Free lưu trong RAM và mất state nếu chính Redis restart; phép thử restart agent ở CP5 không chứng minh độ bền qua restart datastore. Xem [Render Free](https://render.com/docs/free).

## Deployment Issue and Resolution

Lần đầu build thất bại ở `CGO_ENABLED=0 go build -o myapp .` vì Root Directory chưa đặt, Render dùng Dockerfile Go ở gốc repo. Sau khi đổi Root Directory sang `06-lab-complete`, dashboard xác nhận deploy thành công commit `c17b3e2`. Không sửa Dockerfile Go của bài Docker để khắc phục cấu hình cloud.

## Screenshots

- [Dashboard](screenshots/dashboard.png) hiển thị lượt triển khai thành công.
- [Dịch vụ đang chạy](screenshots/running.png) hiển thị trạng thái Live và URL public.
- [Kết quả kiểm tra](screenshots/test.png) hiển thị 4/4 phép thử PASS.
