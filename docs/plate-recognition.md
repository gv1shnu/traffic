# License plate recognition

The selected vehicle's clearest observations are sampled, cropped, and passed to a separate YOLOv8 license-plate detector. Its measured detection score remains separate from OCR confidence. A crop needs at least 48×12 source pixels. Conservative CLAHE and 2× cubic scaling precede EasyOCR; no character substitution or generative enhancement occurs.

Spatially ordered OCR words are combined, preserving their raw text and timestamps. Multi-frame consensus applies configured regex patterns and checks detector confidence, minimum OCR confidence, visual quality and agreement. Two distinct frames normally must agree; an exceptionally clear frame needs higher independent thresholds. Duplicate text from the same timestamp is not counted twice. Conflicting or partial results remain unreadable with `text: null`; raw readings remain separate, uncertain evidence.

Default patterns cover ordinary Indian state/RTO registration strings and BH-series strings. They accept examples `KA01AB1234`, `DL8CAF5031`, `TS09EX1234`, and `22BH1234AA`. This is format filtering, not registration verification. Edit `plate_patterns` for other regions or additional legitimate formats. Two-line layouts and severe perspective remain challenging. There is no registration database lookup.

Without accepted OCR, the best annotated subject frame and its unannotated counterpart are produced. Unknown causes instead receive representative congestion frames. Evidence quality combines sharpness, exposure, contrast, subject size, detector score and boundary clearance; it does not directly measure occlusion or pose. Redacted exports blur detected non-selected subjects while retaining the selected subject. Original media is not redacted.

## Models

Run `python scripts/download_models.py --ocr`. The script obtains YOLO11n, a pinned [public YOLOv8 plate model](https://huggingface.co/Koushim/yolov8-license-plate-detection), and official [EasyOCR](https://github.com/JaidedAI/EasyOCR) English model files. The plate weight is SHA-256 verified. Weights live under ignored `models/`, not Git. Missing detector weights fail analysis with an actionable message; missing optional plate/OCR weights produce a visible limitation and null plate result.

The public plate model has not been validated here on Indian surveillance plates. No real-world plate accuracy is claimed. Generic plate detection must be evaluated on Indian fonts, commercial yellow plates, two-line registrations, glare, motorcycles and small distant plates. Model/package licenses apply independently; see `docs/data-sources.md`.
