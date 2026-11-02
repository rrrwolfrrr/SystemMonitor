import unittest

from schema import validate_raw_sensor, validate_sensor_payload


class SensorSchemaTests(unittest.TestCase):
    def test_unknown_sensor_is_retained_by_the_public_shape(self):
        sensor = {
            "hardware": "Board", "subhardware": None, "type": "VendorThing",
            "name": "Mystery", "value": None, "unit": "unknown",
            "identifier": "board/mystery",
        }
        self.assertTrue(validate_raw_sensor(sensor))
        self.assertTrue(validate_sensor_payload({"sensors": [sensor]}))

    def test_missing_identity_is_rejected(self):
        self.assertFalse(validate_raw_sensor({"type": "Temperature"}))
