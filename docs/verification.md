# Verification performed

Development verification used Python 3.12, Node, FFmpeg, local PostgreSQL, Redis and a Celery worker on macOS arm64. Docker and CUDA execution were not available on this host.

| Check | Result |
|---|---|
| Backend tests | 36 passed |
| Frontend tests | 8 passed |
| Ruff lint and formatting | Passed |
| mypy (API, worker, packages) | Passed |
| ESLint | Passed |
| TypeScript + Vite production build | Passed |
| Python dependency lock consistency | Passed |
| Browser upload → configuration → live job → report | Passed with real inference on generated footage |
| Browser human review persistence | Passed |
| Mobile layout/navigation | Inspected at 390×844, no horizontal overflow |
| Actual plate detector + EasyOCR loading | Passed; blank image correctly returned no reading |
| Native infrastructure smoke after final backend changes | Passed in 6.07 seconds for an 18-second synthetic clip |
| Indian public-data detection evaluation | Executed on four attributed UVH-26 images; see evaluation-results.json |
| Compose YAML | Parsed; service topology/loopback binding checked |
| Docker Compose build/run | Not executed locally; CI job supplied |
| GPU execution | Not tested |

The native infrastructure smoke measured an actual asynchronous job through HTTP upload, PostgreSQL persistence, Redis dispatch, Celery execution, model inference, evidence retrieval and a saved review. Its input was visibly synthetic footage and yielded zero detections, no congestion and a null plate. This validates integration, not detection recall or real incident accuracy.

Separate backend tests inject synthetic observations and OCR only inside test code to exercise known cause selection, plate acceptance/rejection, evidence assets, ambiguity, errors, review corrections and cleanup. Production never selects these adapters.

The public still-image evaluation used real YOLO inference. Four images yielded 56.25% precision and 50% recall at IoU 0.5 under the documented class mapping. This sample is too small and narrow for field-performance claims. No real Indian plate, temporal identity or cause-attribution benchmark was evaluated.

One upstream Starlette/AnyIO deprecation warning was emitted during pytest; no tests failed.
