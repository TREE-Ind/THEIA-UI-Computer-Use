# Plugin design

Hermes directory plugins are cloned to `~/.hermes/plugins/<name>` and must
expose:

- `plugin.yaml`
- `__init__.py` with `register(ctx)`

This plugin keeps all runtime code in the plugin directory. It registers tools
via `ctx.register_tool(...)` so Hermes tracks them as plugin-provided.

LocateAnything dependencies are optional and should live in an external venv.
The basic PyAutoGUI tools should remain available even when ML packages are
missing.

## Persistent LocateAnything architecture

```text
Hermes tool call
  -> one persistent Python JSONL worker (request IDs + serialized transaction)
    -> one loaded locate_anything DLL / Engine / CUDA context
      -> exact screenshot preparation cache (decode/preprocess/ViT/projector)
      -> independent prompt decoding or validated multi-category PBD
```

The native engine is deliberately non-reentrant. One lock owns the complete
request/response transaction; parallel detection means shared image preparation
and model-level PBD, not multiple competing GPU engines. Any timeout or worker
code/config change discards the old process and its response queue. Worker EOF
is signaled immediately to blocked callers so a crashed process cannot consume
the full inference timeout.

The batch-locate cache is content-specific. Different pixels, crops, resize
dimensions, preprocessing options, model identities, or inference modes must not
share a prepared image. Refinement crops are independent tensors and therefore
require their own preparation.

Symbolic computer-use batches resolve every target before action one and require
an explicit immutable-screen acknowledgement. Layout-changing actions terminate
the stage; callers must capture and resolve a new stage afterward. Safety impact
screening covers both caller hints and authoritative symbolic descriptions.
