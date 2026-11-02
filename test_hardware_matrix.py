"""Static and optional live checks for the hardware sensor matrix."""

import json
import os
import unittest

from schema import validate_raw_sensor


ROOT = os.path.dirname(os.path.abspath(__file__))
MATRIX_PATH = os.path.join(ROOT, "hardware_test_matrix.json")


def load_matrix():
    with open(MATRIX_PATH, "r", encoding="utf-8") as stream:
        return json.load(stream)


class HardwareMatrixTests(unittest.TestCase):
    def test_matrix_is_valid_and_complete(self):
        matrix = load_matrix()
        self.assertEqual(matrix.get("schema"), 1)
        cases = matrix.get("cases")
        self.assertIsInstance(cases, list)
        self.assertGreater(len(cases), 0)

        ids = set()
        for case in cases:
            with self.subTest(case=case.get("id")):
                self.assertTrue(case.get("id"))
                self.assertNotIn(case["id"], ids)
                ids.add(case["id"])
                self.assertTrue(case.get("hardware"))
                self.assertIsInstance(case.get("types"), list)
                self.assertTrue(case["types"])

    def test_matrix_rules_match_validator_contract(self):
        from validator import is_valid_reading

        for case in load_matrix()["cases"]:
            for sensor_type in case["types"]:
                field = sensor_type.lower()
                if sensor_type == "Temperature":
                    self.assertFalse(is_valid_reading(
                        "cpu.temperature", 0.0,
                    ), case["id"])
                elif sensor_type == "Load":
                    self.assertTrue(is_valid_reading("cpu.load", 0.0), case["id"])

    def test_raw_sensor_examples_follow_public_schema(self):
        for case in load_matrix()["cases"]:
            sensor = {
                "hardware": case["hardware"],
                "subhardware": None,
                "type": case["types"][0],
                "name": case["id"],
                "value": None,
                "unit": "unknown",
                "identifier": "matrix/" + case["id"],
            }
            self.assertTrue(validate_raw_sensor(sensor), case["id"])

