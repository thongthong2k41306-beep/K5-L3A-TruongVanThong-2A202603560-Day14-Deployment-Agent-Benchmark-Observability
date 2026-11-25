# Benchmark & Observability Report — Day 14

- **Họ tên** Trương Văn Thông
- **Ngày chạy** 25/11/2026, GMT+7
- **Môi trường** Ubuntu 24.04 trên WSL2, 12 CPU logic và tổng 7.785 MiB RAM theo `free -m`. Agent dùng `mock-llm-small`. Client và server cùng máy, giao tiếp HTTP loopback.

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng |
|---|---|---|
| p95 latency `/ask` | ≤ 500 ms | Giữ ít nhất khoảng 95% phản hồi trong nửa giây và nhận ra khi nhóm phản hồi chậm đủ lớn. |
| Error rate `/ask` | ≤ 2% | Mức mặc định của bài lab, dùng để đo tác động của lỗi upstream mô phỏng. |
| Accuracy trên golden dataset | CI ≥ 85%, bài sửa KB đạt 100% và không regression | CI đặt mức tối thiểu và so với baseline để phát hiện câu từng đúng bị sai. Bài sửa KB phải đạt đủ 23 câu. |

## 2. Benchmark hiệu năng (develop)

### 2.1 Concurrency vs latency (agent v2)

Mỗi hàng gửi 300 request với `MOCK_SLOW_RATE=0.03` và `MOCK_ERROR_RATE=0.01`. RPS tính trên toàn bộ request, latency tính trên phản hồi HTTP 200.

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO | JSON |
|---:|---:|---:|---:|---:|---:|---|---|
| 1 | 4,82 | 201,5 | 224,7 | 237,3 | 1,67% | PASS | [c1](reports/load_v2_c1.json) |
| 10 | 36,04 | 223,3 | 318,4 | 1.700,6 | 0,00% | PASS | [c10](reports/load_v2_c10.json) |
| 50 | 67,17 | 486,3 | 693,3 | 1.849,6 | 1,00% | FAIL p95 | [c50](reports/load_v2_c50.json) |
| 100 | 42,64 | 1.063,6 | 5.303,4 | 5.917,2 | 0,67% | FAIL p95 | [c100](reports/load_v2_c100.json) |

RPS tăng đến 67,17 ở concurrency 50 rồi giảm còn 42,64 ở 100, trong khi p95 tăng lên 5.303,4 ms. Chạy nhiều request cùng lúc giúp chồng thời gian chờ LLM mô phỏng, nhưng ở concurrency cao, client và một worker server cùng chia sẻ tài nguyên máy. Kết quả phù hợp với hiện tượng chờ và tranh tài nguyên, chưa đủ để xác định nút thắt cụ thể. Concurrency 10 là mức cao nhất trong bốn mức thử đạt cả hai SLO.

### 2.2 Tail latency

Mỗi lượt chạy 300 request với concurrency 20 và `MOCK_ERROR_RATE=0.01`. v2 được khởi động lại trước khi đổi tỉ lệ request chậm.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) | JSON |
|---:|---:|---:|---:|---|
| 0 | 313,7 | 480,4 | 549,3 | [0%](reports/load_v2_slow_0.json) |
| 0.03 | 315,3 | 489,0 | 1.729,2 | [3%](reports/load_v2_slow_0.03.json) |
| 0.1 | 364,2 | 1.721,8 | 1.754,2 | [10%](reports/load_v2_slow_0.1.json) |

Từ 0% lên 3%, avg chỉ tăng 1,6 ms, trong khi p99 tăng 1.179,9 ms. Các phản hồi chậm nằm ở đuôi phân bố, nên chúng có trọng số nhỏ trong giá trị trung bình. Ở 10%, nhóm chậm đủ lớn để p95 tăng lên 1.721,8 ms và trượt SLO. Đặt SLO theo p95 và theo dõi thêm p99 để thấy các đợt chậm hiếm hơn. Các lượt chạy có jitter ngẫu nhiên, nên số đo sẽ dao động khi chạy lại.

### 2.3 Đọc metrics (Exercise 7.1)

Request hỏi cách Prometheus thu thập metrics trả về `request_id=f7f658888ad8`, 91 input token, 55 output token và chi phí mock 0.00004665 USD. Xem [response thực tế](reports/ask_sample.json) và [output metrics](reports/metrics_sample.txt).

- Counter `http_requests_total{method="POST",route="/ask",status="200"}` ghi nhận một request thành công.
- Gauge `agent_in_flight_requests` tăng khi bắt đầu xử lý và giảm sau khi kết thúc.
- Histogram `http_request_duration_seconds` ghi vào các bucket để Prometheus ước lượng percentile.

`route.path` gom các URL theo mẫu route. URL lạ cùng được gán `unmatched`. Nếu đưa URL thật vào label, hàng nghìn đường dẫn ngẫu nhiên tạo ra hàng nghìn time series, làm tăng RAM và chi phí truy vấn. Histogram `agent_question_length_chars` ghi nhận số ký tự trước khi xử lý LLM, gom theo bucket thay vì tạo label cho từng độ dài. Sau khi gửi một câu `Hello`, [metrics của histogram](reports/metrics_question_length.txt) ghi `count=1` và `sum=5`.

## 3. Benchmark chất lượng (develop)

Chạy cùng golden dataset gồm 23 câu. Các lượt eval đặt `MOCK_ERROR_RATE=0` và `MOCK_SLOW_RATE=0` để tập trung đo chất lượng câu trả lời. Công cụ chấm câu đúng khi khớp ít nhất 60% từ khóa mong đợi.

| Chỉ số | [Agent v1](reports/eval_v1.json) | [Agent v2](reports/eval_v2.json) | [v2 sau khi sửa KB](reports/eval_v2_fixed.json) |
|---|---:|---:|---:|
| Accuracy | 4,35% (1/23) | 91,30% (21/23) | 100% (23/23) |
| Avg tokens / câu | 58,0 | 109,0 | 116,4 |
| Tổng cost (USD) | 0,000417 | 0,000760 | 0,000814 |
| Cost / câu đúng (USD) | 0,00041715 | 0,00003619 | 0,00003540 |
| Latency p95 (ms) | 194,9 | 220,4 | 227,1 |
| Quality gate | FAIL (80%) | PASS (80%, 0 regression) | PASS (100%, 0 regression) |

Retrieval thêm thời gian xử lý và đưa tài liệu vào prompt, làm tổng token và chi phí mock tăng. Bản v2 sau khi sửa tốn khoảng 1,95 lần tổng chi phí v1 trên 23 câu nhưng chi phí cho mỗi câu đúng thấp hơn khoảng 11,8 lần. p95 tăng 32,2 ms trong lần eval này. Kết quả chất lượng áp dụng cho bộ 23 câu và cách chấm theo từ khóa của lab.

| Câu sai ban đầu | Từ khóa thiếu | Chỉnh knowledge base |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm tài liệu về JWT có chữ ký, có thể chứa thời điểm hết hạn và cách đối chiếu với API key. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm tài liệu về Horizontal Pod Autoscaler và các nguồn metric để điều chỉnh số replica. |

### Quality gate trong CI (Exercise 7.3)

Job trên pull request cài dependencies, chạy v2 và chờ `/ready` phản hồi. Đặt `MOCK_ERROR_RATE=0` và `MOCK_SLOW_RATE=0` để gate tập trung vào chất lượng câu trả lời. Dùng baseline từ nhánh đích đã được duyệt, rồi chạy lệnh sau từ `develop/`:

```bash
python eval/run_eval.py --url http://127.0.0.1:8002 --min-accuracy 0.85 \
  --baseline "$BASELINE_JSON" --out reports/eval_ci.json
```

`BASELINE_JSON` trỏ đến báo cáo chất lượng của bản đã duyệt, ví dụ `eval_v2_fixed.json` sau khi CP7 được merge. Không bỏ qua exit code của lệnh. Exit 1 làm job thất bại khi accuracy dưới 85% hoặc có regression. Đặt job làm required status check của nhánh đích để GitHub chặn merge. Lần kiểm thử v1 với baseline v2 trả exit 1 và 20 regression, có trong [eval_v1_regression.json](reports/eval_v1_regression.json).

## 4. Observability stack (production)

Thực hiện ở CP8. Chưa có dữ liệu Grafana, Jaeger hoặc thời gian alert firing trong lần chạy CP7.

## 5. Benchmark scaling (production)

Thực hiện ở CP8 với Locust headless. Các phép thử concurrency ở mục 2 đều chạy một agent local.

## 6. Kết luận

1. Dùng p95/p99 cùng tỉ lệ lỗi để thấy nhóm request bị chậm mà số trung bình làm mờ.
2. Dùng cost trên mỗi câu đúng để so sánh các phiên bản có accuracy chênh lệch lớn.
3. Kết hợp mức accuracy tối thiểu với kiểm tra regression theo từng câu để tránh bỏ sót lỗi khi tổng điểm vẫn đạt.

Khi triển khai thật, theo dõi p99, tỉ lệ timeout và tỉ lệ retrieval không tìm thấy tài liệu. Chạy eval định kỳ trên bộ câu hỏi cố định để phát hiện suy giảm chất lượng khi health và latency vẫn ổn.
