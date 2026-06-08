# LocateAnything-3B loader notes for Windows Computer Use

This reference captures the working loading path and known pitfalls for `nvidia/LocateAnything-3B` inside the Windows computer-use backend.

Verified dependencies:
- `torch`
- `transformers==4.57.1`
- `peft==0.19.1`
- `sentencepiece`
- `lmdb`
- `decord`
- `hf_xet`

Failing patterns to avoid:
- `AutoModelForZeroShotObjectDetection`
- `post_process_grounded_object_detection`

Working pattern:
- `AutoProcessor.from_pretrained(..., trust_remote_code=True)`
- `AutoTokenizer.from_pretrained(..., trust_remote_code=True)`
- `AutoModel.from_pretrained(..., trust_remote_code=True)`
- Chat-template inference via `processor(text=..., images=..., return_tensors="pt")` then `model.generate(...)` and `processor.batch_decode(...)`
- Extract boxes from generated tags.

Parser robustness:
- Expected tags include both `<bbox>...</bbox>` and `<box>...</box>` from different checkpoints.
- Degenerate boxes with non-positive width/height must be filtered out.
