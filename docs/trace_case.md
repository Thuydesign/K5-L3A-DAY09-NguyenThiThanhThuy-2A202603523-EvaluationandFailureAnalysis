# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Case đã phân tích

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`; report `E-seeded_regression-20261117-7ed0` |
| Triệu chứng | `trial_pass` fail: agent resolve và ledger ghi 20.000đ, trong khi label yêu cầu denied và 0đ. |
| Bước sai đầu tiên | Event 3 `model_override`: `{"delay_days": 5}`. |
| Vì sao là bước *đầu tiên* | Event 1 handoff giới hạn tool; event 2 đọc đúng DB: O-202 có delay 2 ngày. Sai lệch chỉ bắt đầu ở event 3 khi ticket đè giá trị DB. Event 4 quote 20.000đ và event 5 gọi host là hậu quả. |
| Failure mode | FM-03 `ticket_trust`. |
| Đối chứng | `fixed C-002@11`: event 3 là quote `no_entitlement` 0đ, không có `model_override`; ledger 0đ và trial PASS. |
| Regression test | `test_seeded_ticket_override_regression_has_fixed_control`: xác nhận fail trên `seeded_regression`, pass trên `fixed`; metric `pass_rate` chặn biến thể. |
| Chưa chắc chắn | Trace chứng minh thứ tự event và kết quả của seed này; không khẳng định tần suất lỗi trên model thật hoặc claim khác. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
