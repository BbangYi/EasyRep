"""Fixed native-fixture observations, not device timing or hydraulic evidence."""
import unittest

from habitat.control.r15_timing import request_timing, TIMING_PROFILE, REQ_MAX_MS, RUN_MAX_S


class R15TimingTests(unittest.TestCase):
    def test_observed_native_phase_sweep_matches_forward_profile(self):
        # check_cage_node's frozen Pico + real ESP bridge recorded these ranges.
        observations = {2000: (959, 979), 3000: (1959, 1979),
                        4000: (2959, 2979), 4500: (3000, 3000), 5000: (3000, 3000)}
        for hold, (at_boundary, between_ticks) in observations.items():
            for phase in range(20):
                with self.subTest(hold=hold, phase=phase):
                    result = request_timing(hold, 400 + phase)
                    self.assertEqual(result['request_rise_ms'], 420)
                    self.assertEqual(result['qualified_ms'], 440)
                    self.assertEqual(result['trigger_ms'], 1440)
                    self.assertEqual(result['run_start_ms'], 1441)
                    expected_ms = between_ticks if phase else at_boundary
                    self.assertAlmostEqual(result['expected_virtual_run_s'], expected_ms / 1000)
                    self.assertEqual(result['run_end_ms'], 1441 + expected_ms)
                    self.assertEqual(result['request_fall_ms'], 400 + hold + (20 if phase else 0))

    def test_phase_zero_plan_is_translation_of_native_fixture(self):
        self.assertEqual(TIMING_PROFILE, 'r15_esp20_pico_window1ms_phase0_v1')
        self.assertEqual((REQ_MAX_MS, RUN_MAX_S), (5000, 3))
        for hold, expected in ((2000, .959), (3000, 1.959), (4000, 2.959), (4500, 3.), (5000, 3.)):
            with self.subTest(hold=hold):
                result = request_timing(hold)
                self.assertEqual(result['run_start_ms'], 1041)
                self.assertEqual(result['expected_virtual_run_s'], expected)

    def test_short_requests_never_invent_reached_phases_or_positive_run(self):
        for hold in (0, 1, 20):
            with self.subTest(hold=hold):
                result = request_timing(hold)
                self.assertIsNone(result['request_rise_ms'])
                self.assertIsNone(result['request_fall_ms'])
                self.assertIsNone(result['run_start_ms'])
                self.assertEqual(result['expected_virtual_run_s'], 0.)
        result = request_timing(40)
        self.assertEqual((result['request_rise_ms'], result['request_fall_ms']), (20, 40))
        self.assertIsNone(result['qualified_ms'])
        for hold in (1000, 1040):
            result = request_timing(hold)
            self.assertEqual(result['qualified_ms'], 40)
            self.assertIsNone(result['trigger_ms'])
            self.assertIsNone(result['run_end_ms'])
            self.assertEqual(result['expected_virtual_run_s'], 0.)

    def test_rejects_coercion_and_invalid_millisecond_ranges(self):
        for hold in (True, False, 1., '2000', None, -1, 5001):
            with self.subTest(hold=hold), self.assertRaises(ValueError):
                request_timing(hold)
        for receipt in (True, False, 0., '0', None, -1):
            with self.subTest(receipt=receipt), self.assertRaises(ValueError):
                request_timing(2000, receipt)


if __name__ == '__main__':
    unittest.main()
