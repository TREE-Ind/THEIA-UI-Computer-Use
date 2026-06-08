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
