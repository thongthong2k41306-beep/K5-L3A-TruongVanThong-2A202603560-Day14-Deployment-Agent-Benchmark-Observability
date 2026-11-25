"""Copy measured CP5 evidence into the lab answers without editing the checker."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
answers = ROOT / "MISSION_ANSWERS.md"
text = answers.read_text(encoding="utf-8")
output = (ROOT / "reports/cp5-production-ready.txt").read_text(encoding="utf-8")
checklist = output[output.index("  📋 Checklist Deliverable"):].strip()
section = """## Part 6 — Final Project (CP5)

Đã hoàn thiện agent trong `06-lab-complete/` và chạy bản checker đầy đủ trong Ubuntu WSL2 với Docker ngày 25/11/2026 lúc 15:54 GMT+7. Kết quả: **PASS 12/12, 43/43 checks**, exit code 0. Log gốc: [cp5-production-ready.txt](reports/cp5-production-ready.txt); metadata và SHA256: [cp5-runtime.json](reports/cp5-runtime.json).

### Các bước thực hiện và mục đích

| Bước | Thực hiện | Mục đích |
|---|---|---|
| 1 | Đọc/kiểm tra biến môi trường trong `app/config.py`; chỉ lưu tên biến và giá trị mẫu trong `.env.example`. | Thay cấu hình theo môi trường và tránh đưa secret lên Git. |
| 2 | Kiểm tra header `X-API-Key` bằng phép so sánh hằng thời gian; key thiếu/sai trả 401. | Chặn truy cập chưa được cấp quyền. |
| 3 | Tách `/health` luôn trả 200 khỏi `/ready` kiểm tra Redis và trả 503 khi phụ thuộc lỗi. | Phân biệt process còn sống với ứng dụng sẵn sàng nhận request. |
| 4 | Rate limit rolling window 60 giây bằng Redis sorted set và Lua atomic. | Nhiều worker cùng chia sẻ giới hạn, tránh vượt ngưỡng khi request đến đồng thời. |
| 5 | Cost guard đặt trước chi phí tối đa của mock bằng Lua, sau đó quyết toán chi phí thật và hoàn phần dư. | Ngăn nhiều request cùng vượt ngân sách; hết ngân sách trả 402. |
| 6 | Ngân sách theo ngày UTC, số tiền lưu dạng số nguyên nanodollar trong Redis. | Tránh sai số cộng tiền và dùng chung bộ đếm qua restart agent. |
| 7 | Log JSON gồm request ID, route, status và thời gian; không ghi API key hay nội dung câu hỏi. | Theo dõi lỗi/thời gian xử lý mà không ghi secret vào log. |
| 8 | Docker multi-stage, user `agent`, Uvicorn nhận SIGTERM qua `exec`, hai worker. | Image nhỏ, chạy non-root và chờ request đang xử lý trước khi tắt. |
| 9 | Compose gồm agent + Redis AOF, named volume; chuẩn bị `railway.toml` và `render.yaml`. | Tái lập stack local và cấu hình triển khai cloud cho CP6. |

Giới hạn: chi phí và token là ước lượng của mock, không phải hóa đơn LLM thật. Mức giữ trước dùng độ dài tối đa của các câu trả lời mock đã biết; khi thay bằng LLM thật cần giới hạn output và tính lại khoản giữ trước. Nếu process chết sau khi giữ tiền, khoản giữ trước được giữ theo hướng thận trọng tới khi ledger hết hạn. Redis Free trên cloud không được coi là lưu trữ bền vững qua restart chính Redis.

### Checklist Deliverable — trích nguyên output checker

```text
""" + checklist + """
```

`--static-only` đạt 28/28 kiểm tra tĩnh nhưng chỉ tính 3/12 tiêu chí, exit code 1 vì chưa chạy các phép thử runtime. Kết quả nộp là bản đầy đủ 12/12 ở trên. Không sửa `check_production_ready.py` và `golden_dataset.jsonl`; script đối chiếu với Git và lưu SHA256 trong metadata.

### Kiểm tra bổ sung trên Compose thật

Nguồn: [cp5-probes.json](reports/cp5-probes.json), chạy ngày 25/11/2026 lúc 15:49 GMT+7 bằng `scripts/probe-cp5.py`.

| Phép thử | Kết quả đo được |
|---|---|
| Thiếu/sai API key | Cả hai trả 401. |
| Thiếu/rỗng/toàn khoảng trắng/quá dài question; JSON sai | 5 trường hợp trả 422. |
| 40 request, concurrency 20, limit 5/phút | 5 mã 200 + 35 mã 429; restart agent vẫn trả 429. |
| Pause Redis | `/health` 200, `/ready` 503, `/ask` 503; unpause thì ready trở lại 200. |
| 40 request, concurrency 20, budget 0.00005 USD | 4 mã 200 + 36 mã 402; chi phí 0.000045 USD, không vượt budget. |
| Image | 286,295,171 byte = 286.30 MB = 273.03 MiB; user `agent`. |
| Process và log | PID 1 là Uvicorn; 44 dòng log app là JSON hợp lệ, không chứa key thử. |
| Dọn môi trường | Đã tắt stack thử và xóa volume riêng của phép thử. |

Lần probe đầu chờ HTTP readiness nhưng Docker health status của Redis chưa cập nhật kịp, khiến bước recreate service thất bại. Đã sửa script để chờ cả Redis Docker health status; chạy lại toàn bộ probe thành công. Không thay đổi ứng dụng để né lỗi kiểm tra.

### Chạy lại

Trong Ubuntu, từ gốc repository:

```bash
.venv/core/bin/python scripts/run-cp5.py
.venv/core/bin/python scripts/probe-cp5.py
```

Hoặc kích hoạt môi trường core, vào `06-lab-complete/` rồi chạy `python check_production_ready.py`. Mốc “Public URL ready” của checker xác nhận cấu hình có sẵn; URL public chạy thật và ảnh triển khai thuộc CP6, chưa được chứng minh bằng kết quả CP5.

"""
if "## Part 6 — Final Project (CP5)" not in text:
    text = text.replace("## AI log", section + "## AI log", 1)
    text += """

### CP5 — Ngày 25/11/2026

- **Yêu cầu:** hoàn thiện CP5 và tiếp tục CP6 trên Render.
- **Hỗ trợ nhận được:** công cụ AI triển khai các module TODO, Docker/Compose và cấu hình cloud, cập nhật hướng dẫn chạy và soạn báo cáo từ file kết quả thực tế.
- **Kiểm tra với hỗ trợ AI:** chạy checker gốc đầy đủ đạt 12/12, 43/43; thử thêm xác thực, dữ liệu đầu vào, request đồng thời, restart agent, Redis mất kết nối, budget và log. Các số đo lấy từ report đã lưu, không tự đặt.
- **Phần tự kiểm tra của người học:** chưa có kết quả CP5 tự chạy được cung cấp trong hội thoại; cần đọc code và chạy lại để giải thích từng tiêu chí. Không sửa checker hoặc golden dataset.
"""
    answers.write_text(text, encoding="utf-8")
guide = ROOT / "HUONG_DAN_SETUP.txt"
guide_text = guide.read_text(encoding="utf-8")
if "7. KẾT QUẢ CP5" not in guide_text:
    guide.write_text(guide_text + """

7. KẾT QUẢ CP5 NGÀY 25/11/2026

Part 6 đã hoàn thiện, thay cho trạng thái TODO ban đầu ở mục 5.
Checker đầy đủ với Docker: PASS 12/12, 43/43 checks, exit code 0.
Xem reports/cp5-production-ready.txt và MISSION_ANSWERS.md mục Part 6.
Từ gốc repository trong Ubuntu chạy lại:
  .venv/core/bin/python scripts/run-cp5.py
Kiểm tra bổ sung Compose/Redis và request đồng thời:
  .venv/core/bin/python scripts/probe-cp5.py
CP6 chọn Render, cần deploy code mới lên cloud và kiểm tra URL public thật.
""", encoding="utf-8")
print("CP5 report and setup guide updated.")
