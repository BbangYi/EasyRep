"""Forward timing for one native ESP/Pico software fixture, not physical evidence.

Matches tests/hardware/check_cage_node.py: a strict next 20ms ESP task sample,
1ms Pico loop, healthy/armed pins, and an ideal WINDOW rising 1ms after TRIG.
There is no task jitter, analog protection model, hydraulic calibration or RUN
feedback here. Receipt times are non-wrapping fixture milliseconds. A zero hold
means no request in a plan; it is not a valid ON command for the ESP.
"""

TIMING_MODE = "r15_request_fixture"
TIMING_PROFILE = "r15_esp20_pico_window1ms_phase0_v1"
REQ_MAX_MS = 5000
RUN_MAX_S = 3
TICK_MS = 20
QUALIFICATION_MS = 20
PREOPEN_MS = 1000
WINDOW_ACK_MS = 1
LOW_STABLE_MS = 20
RECYCLE_MS = 7000
REQUEST_CANDIDATES_MS = (2000, 3000, 4000, 4500, 5000)


def request_timing(hold_ms, receipt_ms=0):
    """Return actual fixture event times, leaving unreached phases as None."""
    if type(hold_ms) is not int or not 0 <= hold_ms <= REQ_MAX_MS:
        raise ValueError("request hold must be an integer from 0 to 5000ms")
    if type(receipt_ms) is not int or receipt_ms < 0:
        raise ValueError("receipt must be a nonnegative integer fixture millisecond")
    result = {
        "request_hold_ms": hold_ms, "receipt_ms": receipt_ms,
        "request_rise_ms": None, "qualified_ms": None, "trigger_ms": None,
        "run_start_ms": None, "request_fall_ms": None, "run_end_ms": None,
        "expected_virtual_run_s": 0.0,
    }
    rise = (receipt_ms // TICK_MS + 1) * TICK_MS
    fall = ((receipt_ms + hold_ms + TICK_MS - 1) // TICK_MS) * TICK_MS
    if not hold_ms or fall <= rise:
        return result  # Deadline check precedes the GPIO write; REQ never goes HIGH.
    result.update(request_rise_ms=rise, request_fall_ms=fall)
    qualified = rise + QUALIFICATION_MS
    if fall <= qualified:
        return result
    result["qualified_ms"] = qualified
    trigger = qualified + PREOPEN_MS
    if fall <= trigger:
        return result  # REQ LOW during PREOPEN enters DRAIN without TRIG or RUN.
    result["trigger_ms"] = trigger
    start = trigger + WINDOW_ACK_MS
    if fall <= start:
        return result
    end = min(fall, start + RUN_MAX_S * 1000)
    result.update(run_start_ms=start, run_end_ms=end,
                  expected_virtual_run_s=(end - start) / 1000)
    return result
