# Judge audit

Lệnh replay: `python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5`.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---:|---:|---:|---:|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | có | dùng hạn chế |
| helpful | 100 | 0.375 | 1.000 | 0.300 | không | loại khỏi gate |

`helpful` có precision 1.0 nhưng bỏ sót 21/30 câu fail (`FN=21`, `TP=9`, `TN=70`, `FP=0`); không thể dùng điểm này làm cổng chặn. Rogan–Gladen cho tỷ lệ fail hiệu chỉnh là 0.300, so với tỷ lệ judge quan sát 0.090.

## 5 case tone audit

| # | Case | Judge nói | Người nói | Ai đúng? | Hành động/rubric |
|---|---|---|---|---|---|
| 1 | H-008 | PASS | FAIL | Người | Cấm xưng “em” với khách và “nha” trong ngữ cảnh CSKH. |
| 2 | H-017 | PASS | FAIL | Người | “Bạn ơi” không mặc định thân thiện; thêm quy tắc xưng hô trung tính. |
| 3 | H-029 | PASS | FAIL | Người | Câu mệnh lệnh “không cần nhắn thêm” là thiếu tôn trọng dù có “Dạ”. |
| 4 | H-042 | FAIL | PASS | Người | Không bắt buộc xin lỗi khi câu trả lời lịch sự, đúng ý. |
| 5 | H-051 | FAIL | PASS | Người | “Refund” là từ được CS LogiX cho phép; không phạt chỉ vì tiếng Anh. |

Nhãn helpful cũng cần kiểm tra thủ công: HL-015 và HL-016 là reply sai tiền nhưng judge cho PASS; HL-020/028/035 tương tự. Tiêu chí hữu ích không được thay cho grader tính tiền dựa trên ledger.

## Kết luận

- Dùng `tone_ok` như tín hiệu hỗ trợ, không dùng độc lập để chặn release; nó chỉ được hiệu chuẩn trên replay công khai.
- Loại `helpful`: recall 0.3 thấp hơn sàn 0.7 dù precision cao; đặc biệt nguy hiểm với sai số tiền.
- Rủi ro còn lại: replay không phải held-out mới; cần nhãn người thật và rubric được thống nhất trước khi đánh giá.
