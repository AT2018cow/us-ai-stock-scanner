"""Event interval exposure is retrospective ONLY, with deterministic geometry."""
from __future__ import annotations

import unittest

import pandas as pd

from scripts.mvp_v11_event_exposure_preflight import build_event_interval_flags


def _source():
    data = pd.DataFrame([
        {"signal_date": "2024-01-31", "symbol": "HXL",
         "label_end_20": "2024-02-28", "label_end_60": "2024-04-30",
         "label_end_120": "2024-07-31", "fwd_ret_60": 100.0},
        {"signal_date": "2024-02-29", "symbol": "HXL",
         "label_end_20": "2024-03-29", "label_end_60": "2024-05-31",
         "label_end_120": "2024-08-30", "fwd_ret_60": -100.0},
        {"signal_date": "2024-01-31", "symbol": "WOLF",
         "label_end_20": "2024-02-28", "label_end_60": "2024-04-30",
         "label_end_120": "2024-07-31", "fwd_ret_60": 0.0},
    ])
    events = pd.DataFrame([
        {"symbol": "HXL", "prev_date": "2024-01-31", "date": "2024-02-29",
         "reason": "SHARE_JUMP_UNEXPLAINED", "null_labels": False},
        {"symbol": "WOLF", "prev_date": "2024-01-31", "date": "2024-02-29",
         "reason": "REORG_JUMP_BACKDATED", "null_labels": True},
    ] + [
        {"symbol": f"STK{i}", "prev_date": "2024-01-31",
         "date": "2024-02-29", "reason": "SUSPECT", "null_labels": False}
        for i in range(50)
    ])
    return data, events


class TestMvpV11EventExposure(unittest.TestCase):
    def test_does_not_inspect_or_change_forward_returns(self):
        data, events = _source()
        flags, result = build_event_interval_flags(data, events)
        self.assertFalse(result["ready_for_candidate_returns"])
        self.assertEqual(len(flags), 9)
        self.assertNotIn("fwd_ret_60", flags)
        before = flags.copy()
        data["fwd_ret_60"] = [999, -999, 1]
        after, _ = build_event_interval_flags(data, events)
        pd.testing.assert_frame_equal(before, after)

    def test_future_interval_does_not_retroactively_censor_new_signal(self):
        data, events = _source()
        flags, _ = build_event_interval_flags(data, events)
        # Event interval = (Jan31, Feb29]; Jan31 signal / Feb28 end intersects.
        earlier = flags[(flags.signal_date == "2024-01-31") &
                        (flags.symbol == "HXL") & (flags.horizon == 20)]
        self.assertTrue(bool(earlier.event_interval_exposed.iloc[0]))
        # Feb29 signal after detected interval: later holding interval cannot overlap.
        later = flags[(flags.signal_date == "2024-02-29") &
                      (flags.symbol == "HXL")]
        self.assertFalse(bool(later.event_interval_exposed.any()))

    def test_bad_interval_and_changed_event_count_fail(self):
        data, events = _source()
        with self.assertRaisesRegex(ValueError, "52-event"):
            build_event_interval_flags(data, events.head(51))
        events.loc[0, "prev_date"] = "2024-03-31"
        with self.assertRaisesRegex(ValueError, "precede"):
            build_event_interval_flags(data, events)

    def test_duplicate_symbols_and_missing_label_end_fail(self):
        data, events = _source()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_event_interval_flags(pd.concat([data, data.head(1)]), events)
        with self.assertRaisesRegex(ValueError, "missing frozen label_end"):
            build_event_interval_flags(data.drop(columns=["label_end_60"]), events)


if __name__ == "__main__":
    unittest.main()
