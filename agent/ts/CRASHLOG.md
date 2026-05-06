## 2026-05-05T20:05:57+01:00

- Crash type: DataLoader worker CUDA initialization crash while loading `.pt` tensors (`c10::AcceleratorError` / `CUDA error: initialization error`)
- Time: 2026-05-05T20:05:57+01:00
- Fix implemented: Forced CPU deserialization with `map_location="cpu"` on worker-side `torch.load(..., weights_only=False)` call sites in `SimpleTorchLoader.__call__`, `TorchReader.read`, and `LoadTorchd.func`.
