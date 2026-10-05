"""Additive actionable failures; never changes existing safety verdicts."""
_RULES = {
    'worker_admission_timeout': ('inspect_worker_status_then_retry_fresh_stage_explicitly', False),
    'worker_recovery_busy': ('wait_for_owned_transaction_to_finish_then_handoff', False),
    'worker_exit_unconfirmed': ('retain_quarantine_and_inspect_owned_worker_exit', False),
    'worker_recovery_authorization_required': ('request_authorization_for_owned_worker_disposal', False),
    'target_missing': ('clarify_target_or_widen_roi', False),
    'readiness_not_met': ('inspect_loading_state_and_wait_with_deadline', False),
    'resident_worker_required': ('warm_native_backend_explicitly', False),
    'resident_native_engine_required': ('warm_native_backend_explicitly', False),
    'worker_reload_required': ('authorize_reload_before_explicit_foreground_warm', False),
    'region_context_changed': ('recapture_and_recalibrate_control_geometry', False),
    'window_changed_during_verification': ('confirm_and_recapture_intended_window', False),
    'wrong_window': ('confirm_and_recapture_intended_window', False),
    'stale_capture': ('recapture_and_reground', False),
    'untrusted_grounding': ('inspect_provenance_and_reground', False),
    'completion_unverified': ('inspect_expected_target_and_handoff', False),
    'checkpoint_unverified': ('inspect_intermediate_state_and_handoff', False),
    'target_wait_timeout': ('inspect_loading_or_missing_target', False),
    'deadline': ('handoff_with_fresh_state', False),
    'missing_dependency': ('install_missing_dependency_outside_live_gateway', False),
    'backend_unavailable': ('check_native_runtime_and_worker_health', False),
    'loading': ('wait_within_declared_deadline', True),
    'not_found': ('clarify_target_or_widen_roi', False),
    'preflight_failed': ('revise_explicit_safe_plan', False),
    'invalid_plan': ('revise_explicit_safe_plan', False),
}


def actionable(result, phase=None):
    if isinstance(result, list):
        return [actionable(item, phase) for item in result]
    if not isinstance(result, dict):
        return result
    result = dict(result)
    if result.get('status') not in {'error','blocked','escalate','installing','in_progress','not_found','stale'}:
        return result
    code = result.get('code') or result.get('reason')
    if not code:
        kind = result.get('error_type', '')
        if kind in {'ModuleNotFoundError','ImportError'}:
            code = 'missing_dependency'
        elif result.get('status') in {'installing','in_progress'}:
            code = 'loading'
        elif result.get('status') == 'stale':
            code = 'stale_capture'
        elif result.get('status') == 'not_found':
            code = 'not_found'
        elif result.get('status') == 'blocked':
            code = 'preflight_failed'
        else:
            code = 'backend_unavailable'
    next_step, retryable = _RULES.get(code, ('inspect_failure_and_handoff', False))
    result.setdefault('code', code)
    result.setdefault('next_step', next_step)
    result.setdefault('retryable', retryable)
    if phase:
        result.setdefault('phase', phase)
    return result
