"""Publication admission: public runtime must not depend on native experiments."""
import ast
from pathlib import Path
import windows_computer_use as ui

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = ('native_encoder_benchmark', 'native_encoder_profile',
            'native_candidate_validation', 'native_kernel_activation')


def test_default_registration_without_experimental_modules():
    class Context:
        def __init__(self): self.tools = []
        def register_tool(self, **kwargs): self.tools.append(kwargs)
    ctx = Context()
    ui.register_tools(ctx)
    names = {tool['name'] for tool in ctx.tools}
    assert 'computer_use_recover_worker' in names
    assert 'computer_use_worker_status' in names
    assert not any(any(token in name for token in EXCLUDED) or
                   name == 'computer_use_activate_native_kernel' for name in names)
    for token in EXCLUDED:
        assert not (ROOT / (token + '.py')).exists()
        assert token not in (ROOT / 'windows_computer_use.py').read_text()
    assert 'exclusive_benchmark' not in ui._worker_transport_status()
