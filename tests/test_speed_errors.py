import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import windows_computer_use as ui


def test_registered_boundary_reports_actionable_missing_dependency():
    def missing(): raise ModuleNotFoundError('Pillow is missing')
    result = json.loads(ui._wrap(missing)({}))
    assert result['code'] == 'missing_dependency'
    assert result['next_step'] == 'install_missing_dependency_outside_live_gateway'
    assert result['retryable'] is False


def test_missing_target_and_loading_readiness_have_distinct_recovery():
    from speed_errors import actionable
    assert actionable({'status':'escalate','code':'target_missing'})['next_step']=='clarify_target_or_widen_roi'
    assert actionable({'status':'escalate','code':'readiness_not_met'})['next_step']=='inspect_loading_state_and_wait_with_deadline'


def test_wrong_window_error_has_recovery_not_autonomous_retry():
    from speed_errors import actionable
    result = actionable({'status':'escalate', 'reason':'wrong_window'})
    assert result['code'] == 'wrong_window'
    assert result['next_step'] == 'confirm_and_recapture_intended_window'
    assert result['retryable'] is False
