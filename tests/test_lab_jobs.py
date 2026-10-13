import tempfile
import unittest
from pathlib import Path

from huntmob.lab_jobs import ArtifactSource, LabRequest, plan_lab


class LabJobTests(unittest.TestCase):
    def test_authorized_apk_produces_app_first_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "lab.apk"
            apk.write_bytes(b"controlled-test-artifact")
            result = plan_lab(LabRequest(
                "eng-1", "br.com.example.lab", ArtifactSource.UPLOAD,
                artifact_path=str(apk), authorized=True, human_approved=True,
            ))
        self.assertTrue(result["ok"])
        self.assertTrue(result["headless"])
        self.assertEqual(result["artifact"]["kind"], "apk")
        self.assertEqual(result["states"][-1], "ready")

    def test_firebase_reference_never_contains_token(self):
        result = plan_lab(LabRequest(
            "eng-1", "br.com.example.lab", ArtifactSource.FIREBASE,
            firebase_release="projects/p/apps/a/releases/r",
            authorized=True, human_approved=True,
        ))
        self.assertTrue(result["ok"])
        self.assertNotIn("token", str(result).lower())

    def test_unapproved_job_is_blocked(self):
        result = plan_lab(LabRequest(
            "eng-1", "br.com.example.lab", ArtifactSource.PLAY_MANUAL,
            authorized=True,
        ))
        self.assertFalse(result["ok"])
        self.assertIn("human approval", " ".join(result["errors"]))


if __name__ == "__main__":
    unittest.main()
