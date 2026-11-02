import os
import tempfile
import unittest

from verify_build import REQUIRED, verify_distribution


class VerifyBuildTests(unittest.TestCase):
    def create_distribution(self, root, dashboard_content):
        distribution = os.path.join(root, "dist")
        internal = os.path.join(distribution, "_internal")
        os.makedirs(internal)
        for relative in REQUIRED:
            if relative == "_internal":
                continue
            path = os.path.join(internal, *relative.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as asset:
                asset.write(
                    dashboard_content
                    if relative == "templates/dashboard.html"
                    else b"asset"
                )
        return distribution

    def test_accepts_distribution_matching_source_dashboard(self):
        with tempfile.TemporaryDirectory() as root:
            source_root = os.path.join(root, "source")
            source_templates = os.path.join(source_root, "templates")
            os.makedirs(source_templates)
            dashboard = b"<button>latest</button>"
            with open(os.path.join(source_templates, "dashboard.html"), "wb") as source:
                source.write(dashboard)
            distribution = self.create_distribution(root, dashboard)

            ok, missing = verify_distribution(distribution, source_root)

        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_rejects_distribution_with_stale_dashboard(self):
        with tempfile.TemporaryDirectory() as root:
            source_root = os.path.join(root, "source")
            source_templates = os.path.join(source_root, "templates")
            os.makedirs(source_templates)
            with open(os.path.join(source_templates, "dashboard.html"), "wb") as source:
                source.write(b"<button>latest</button>")
            distribution = self.create_distribution(root, b"<button>old</button>")

            ok, missing = verify_distribution(distribution, source_root)

        self.assertFalse(ok)
        self.assertIn("templates/dashboard.html (out of date)", missing)


if __name__ == "__main__":
    unittest.main()
