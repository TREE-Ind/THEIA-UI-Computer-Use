"""Real uv workspace admission, no models, Torch install, or GPU required."""
import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hub_124_workspace_admission_retains_isolated_worker(tmp_path):
    uv = shutil.which('uv')
    assert uv, 'uv is required for workspace admission verification'
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname="admission-core"\nversion="0.0.0"\nrequires-python=">=3.11"\n'
        '[project.optional-dependencies]\ntrace-upload=["huggingface-hub==1.24.0"]\n'
        '[tool.uv.workspace]\nmembers=["plugin"]\n')
    plugin = tmp_path / 'plugin'
    plugin.mkdir()
    fixed = (ROOT / 'pyproject.toml').read_text()
    # Reproduce historical UNSELECTED extra conflict against core trace upload.
    old = fixed + '\n[project.optional-dependencies]\nlocate=["transformers==4.57.1"]\n'
    (plugin / 'pyproject.toml').write_text(old)
    (plugin / 'README.md').write_text('admission fixture')
    conflict = subprocess.run([uv, 'lock', '--directory', str(tmp_path)], capture_output=True, text=True)
    assert conflict.returncode != 0
    assert 'huggingface-hub' in conflict.stderr and 'transformers' in conflict.stderr
    (plugin / 'pyproject.toml').write_text(fixed)
    success = subprocess.run([uv, 'lock', '--directory', str(tmp_path)], capture_output=True, text=True)
    assert success.returncode == 0, success.stderr
    lock = tomllib.loads((tmp_path / 'uv.lock').read_text())
    packages = {p['name']: p for p in lock['package']}
    assert packages['huggingface-hub']['version'] == '1.24.0'
    # hf-xet is a legitimate transitive dependency of core's hub 1.24.
    heavy = {'transformers', 'torch', 'peft', 'accelerate', 'decord', 'lmdb'}
    assert not heavy.intersection(packages)
    metadata = tomllib.loads(fixed)['project']
    assert 'locate' not in metadata.get('optional-dependencies', {})
    assert not any(name in dep for dep in metadata['dependencies'] for name in heavy)
    worker = (ROOT / 'requirements-locate.txt').read_text()
    assert 'transformers==4.57.1' in worker and 'peft>=0.13.0' in worker


def test_runtime_has_no_developer_model_fallback():
    source = (ROOT / 'windows_computer_use_locate_worker.py').read_text()
    import re
    assert not re.search('[A-Za-z]:\\\\Users\\\\[^\\\\]+\\\\dev\\\\', source)
