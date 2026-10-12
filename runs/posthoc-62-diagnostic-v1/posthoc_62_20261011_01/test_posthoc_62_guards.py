"""Guards for the isolated post-hoc 62-symbol diagnostic (no network)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from posthoc_62_diagnostic import build_parser, refuse_formal_like


class PosthocGuardTests(unittest.TestCase):
    def test_refuses_formal_token(self) -> None:
        with self.assertRaises(SystemExit):
            refuse_formal_like(Path("outputs/formal_check"))

    def test_refuses_decisions_tree(self) -> None:
        with self.assertRaises(SystemExit):
            refuse_formal_like(Path("outputs/decisions/2026-10-09/risk_off"))

    def test_accepts_isolated_root(self) -> None:
        refuse_formal_like(Path("outputs/posthoc_62"))

    def test_no_formal_flag_exists(self) -> None:
        parser = build_parser()
        self.assertNotIn("--formal", parser._option_string_actions)


if __name__ == "__main__":
    unittest.main()
