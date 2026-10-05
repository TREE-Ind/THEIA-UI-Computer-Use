# Worker transport quarantine and recovery

Correlated JSONL requests share one transaction lock. Expired speculative preparation responses are drained within the bounded transaction deadline and discarded as stale. A drain failure quarantines the transport; timeout never means native cancellation. Source recycling confirms owned-process exit before replacement and fails closed on unconfirmed exit.

`computer_use_worker_status` reads telemetry without capture, restart or native work. `computer_use_recover_worker(authorize=true, timeout_seconds=5)` requires explicit user authorization, applies only to the owned isolated worker, and never restarts the gateway or starts a replacement engine. Busy or unconfirmed-exit states remain blocked. After confirmed recovery, explicitly warm, acquire fresh pixels, and reground before acting.

Local tool invocation uses one local call per `tool_call` envelope. Plugin `steps`/`targets` arrays are only for eligible batch tools. Never loosen stale-stage safety to retry keyboard-only actions blindly.

The optional `scripts/diagnose_worker_quarantine.py <state-db-path>` reads SQLite read-only and emits only whitelisted transport telemetry. It is not part of routine installation and should only read an authorized profile history. See [runtime validation](RUNTIME_VALIDATION.md).
