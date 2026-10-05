# Automatic pixel pipeline

Known-target cpp calls may omit `image_path`; the handler captures fresh pixels internally. This does not eliminate acquisition or establish that the model saw unfamiliar content. Use explicit screenshot evidence and inspect it for unknown content.

Immutable RGB is registered in the parent (two frames, at most 64 MiB). ABI-3 requests use shared RGB on the same serialized worker. Dimensions and digest are verified before preprocessing. Internal `.rgb` identifiers are ephemeral registry keys, not files; evicted memory-only handles fail closed. File-backed captures retain fallback transport. Symbolic actions recheck exact current pixels, bounds, screen origin, window and layout identity before normal safety preflight. No resolution, quantization or decode setting is lowered.

Prefetch is explicit opt-in, one pending latest frame, with a two-second freshness bound. It uses the existing resident worker, never another engine or speculative cold load. Foreground priority is admission priority, not cancellation of an in-flight native operation. Private UI is supported locally; automatic capture does not invoke the optional external decision provider.

Source regression tests validate these contracts using synthetic images and transports. They do not prove live parent activation, GPU performance, or shared-memory portability on other platforms. Parent reload is distinct from worker source recycling. See [runtime validation](RUNTIME_VALIDATION.md).
