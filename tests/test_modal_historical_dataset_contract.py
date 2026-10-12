from __future__ import annotations

import ast
from pathlib import Path
import unittest


RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "modal_baseline_executor.py"


class ModalDatasetKindContractTests(unittest.TestCase):
    def test_output_names_are_kind_isolated_and_legacy_compatible(self) -> None:
        # Import only this pure helper: the GitHub CI environment does not
        # install Modal, and the runner is exercised with credentials later.
        source = ast.parse(RUNNER.read_text(encoding="utf-8"))
        nodes = [
            node for node in source.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_dataset_output_stem"
        ]
        self.assertEqual(len(nodes), 1)
        namespace: dict[str, object] = {}
        module = ast.Module(body=nodes, type_ignores=[])
        exec(compile(module, str(RUNNER), "exec"), namespace)
        stem = namespace["_dataset_output_stem"]
        self.assertEqual(stem("weight", "risk_off"), "weight_dataset_risk_off")
        self.assertEqual(
            stem("company_quality", "risk_off"),
            "company_quality_dataset_risk_off",
        )
        self.assertEqual(
            stem("entry_quality", "risk_off"),
            "entry_quality_dataset_risk_off",
        )
        self.assertEqual(
            stem("entry_quality", "risk_on"),
            "entry_quality_dataset_risk_on",
        )
        with self.assertRaises(ValueError):
            stem("custom", "risk_off")
        with self.assertRaises(ValueError):
            stem("entry_quality", "unknown")


if __name__ == "__main__":
    unittest.main()
