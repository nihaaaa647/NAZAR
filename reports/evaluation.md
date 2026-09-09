# NAZAR injection validation
Run: 2026-09-08T18:51:04.817311+00:00
Real corpus: 5,611 works. Seed: 42.

| Pattern | Caught / trials | Recall | Detector |
|---|---:|---:|---|
| Image reuse | 10/10 | 100% | Byte-identical extracted image matching |
| Cross-year duplicate claim | 10/10 | 100% | Exact normalized cross-year description matching |
| High amount, no evidence | 10/10 | 100% | Missing evidence advisory |

High-amount/no-evidence Isolation Forest recall: 7/10 (70%).
Synthetic sensitivity only; not real-world precision, a fraud finding, or pHash validation. Missing-evidence recall is expected by construction. Ten trials per pattern; the anomaly model is refit on a separate augmented copy.
All injected rows and copied attachments are isolated under reports/synthetic/.
