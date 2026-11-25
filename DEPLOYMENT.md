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

Đã gọi URL public thật, kết quả trong [reports/cp6-public-checks.json](reports/cp6-public-checks.json):

| Request | Mong đợi | Thực tế |
|---|---|---|
| `GET /health` | 200 | 200 |
| `GET /ready` | 200 | 200 |
| `POST /ask`, không có key | 401 | 401 |
| `POST /ask`, có key đúng | 200 | Chưa kiểm tra với key cloud |

**CP6 chưa đủ bằng chứng hoàn tất:** còn phép thử authenticated và lưu các ảnh vào repository. Trạng thái Live lấy từ ảnh trong hội thoại; chưa tạo file ảnh giả hay thay ảnh dashboard bằng hình minh họa.

## Test Commands

Trong Ubuntu, từ gốc repository:

```bash
.venv/core/bin/python scripts/verify-deployment.py
```

Script hỏi `Render AGENT_API_KEY (hidden):`. Copy key từ Environment của Web Service và dán vào terminal; ký tự không hiển thị khi nhập. Script chỉ gửi key tới URL HTTPS đã cấu hình, không lưu key trong báo cáo. Kết quả lưu ở `reports/cp6-runtime.json`, exit code 0 khi đủ 4/4 phép thử đạt.

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

Ảnh Live và URL đã được cung cấp trong hội thoại, nhưng chưa lưu thành các file nộp bài dưới đây. Cần ảnh thật, che giá trị key:

- `screenshots/dashboard.png`: dashboard với deploy thành công.
- `screenshots/running.png`: dịch vụ Live và URL public.
- `screenshots/test.png`: kết quả đủ 4 mã HTTP.
