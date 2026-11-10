"""A settings file for the tests, so the rules they check (the nightly window, the writers' addresses)
do not depend on the machine they run on. Imported first by the tests that need it; unittest discover
loads this module before the others, so one process shares it. Also tests the settings module itself."""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

TEST_SETTINGS = Path(tempfile.mkdtemp(prefix="neovak_test_settings_")) / "settings.toml"
TEST_SETTINGS.write_text('[hold]\nstart = "21:25"\nend = "22:15"\nzone = "America/Chicago"\n'
                         '[writers]\nquick = "http://127.0.0.1:9"\ncareful = "http://127.0.0.1:9"\n'
                         f'[tools]\nmusic_python = "{sys.executable}"\n')
os.environ.setdefault("NEOVAK_SETTINGS", str(TEST_SETTINGS))

from neovak_queue import lanes, memory, settings  # noqa: E402

OVERRIDES = [env for _g, _k, _d, envs, _w in settings.KEYS for env in envs] + ["NEOVAK_EXTRA_HOSTS"]


def clean_environment():
    """Other test modules in the same process set the override variables; these tests read files only."""
    patch = mock.patch.dict(os.environ)
    patch.start()
    for name in OVERRIDES:
        os.environ.pop(name, None)
    return patch


class SettingsFile(unittest.TestCase):
    def setUp(self):
        self.addCleanup(clean_environment().stop)

    def test_defaults_without_a_file(self):
        s = settings.load(Path(tempfile.mkdtemp()) / "none.toml", fresh=True)
        self.assertFalse(s.exists)
        self.assertEqual(s.governor, "")
        self.assertIsNone(s.hold_window())
        self.assertIsNone(s.hold_reason(0))
        self.assertEqual(s.engine_hosts, ["127.0.0.1", "localhost"])
        self.assertEqual(s.hub_cache, Path.home() / ".cache" / "huggingface")

    def test_file_values_and_expansion(self):
        p = Path(tempfile.mkdtemp()) / "s.toml"
        p.write_text('[folders]\noutput = "~/Pictures/NeoVak"\n[models]\nroots = ["~/one", "/two"]\n[memory]\nreserve_gb = 6\n')
        s = settings.load(p, fresh=True)
        self.assertEqual(s.output_dir, Path.home() / "Pictures" / "NeoVak")
        self.assertIn(Path.home() / "one", s.model_roots)
        self.assertEqual(s.reserve_gb, 6.0)
        self.assertEqual(s.origin[("folders", "output")], "file")

    def test_wrong_shape_is_a_plain_error(self):
        p = Path(tempfile.mkdtemp()) / "s.toml"
        p.write_text('[hosts]\nengine = "127.0.0.1"\n')
        with self.assertRaises(settings.SettingsError) as e:
            settings.load(p, fresh=True)
        self.assertIn("should be a list", str(e.exception))

    def test_environment_wins(self):
        p = Path(tempfile.mkdtemp()) / "s.toml"
        p.write_text('[folders]\noutput = "/from/file"\n')
        os.environ["NEOVAK_OUTPUT_DIR"] = "/from/env"
        s = settings.load(p, fresh=True)
        self.assertEqual(str(s.output_dir), "/from/env")
        self.assertIn("NEOVAK_OUTPUT_DIR", s.origin[("folders", "output")])

    def test_hold_window_words_and_states(self):
        s = settings.load(TEST_SETTINGS, fresh=True)
        c = ZoneInfo("America/Chicago")
        self.assertEqual(s.hold_words(), "9:25 PM to 10:15 PM Central")
        self.assertEqual(s.hold_state(0, datetime(2026, 11, 9, 21, 30, tzinfo=c)), "inside")
        self.assertEqual(s.hold_state(600, datetime(2026, 11, 9, 21, 20, tzinfo=c)), "ahead")
        self.assertIsNone(s.hold_state(60, datetime(2026, 11, 9, 21, 20, tzinfo=c)))
        self.assertIsNone(s.hold_state(0, datetime(2026, 11, 9, 22, 15, tzinfo=c)))

    def test_example_file_reads_back(self):
        import contextlib
        import io
        p = Path(tempfile.mkdtemp()) / "example.toml"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(settings.main(["write-example", str(p)]), 0)
            s = settings.load(p, fresh=True)
            self.assertTrue(s.exists)
            self.assertEqual(s.governor, "")
            self.assertEqual(settings.main(["write-example", str(p)]), 1)  # never overwrites


class SimpleMemoryCheck(unittest.TestCase):
    def setUp(self):
        self.addCleanup(clean_environment().stop)
        self.s = settings.load(Path(tempfile.mkdtemp()) / "none.toml", fresh=True)  # no governor named

    def test_reads_vm_stat_text(self):
        text = ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                "Pages free:                               100000.\n"
                "Pages active:                             200000.\n"
                "Pages speculative:                         10000.\n"
                "Pages purgeable:                           20000.\n")
        vm = memory.read_vm_stat(text)
        self.assertAlmostEqual(vm["free"], 100000 * 16384 / 1e9)
        self.assertAlmostEqual(vm["purgeable"], 20000 * 16384 / 1e9)

    def test_simple_check_answers_with_the_governor_shape(self):
        out = memory.preflight(1, self.s)
        self.assertEqual(out["method"], "simple")
        self.assertTrue(out["answered"])
        self.assertIn("VERDICT:", out["report"])
        parsed = memory.parse_report(out["report"])
        self.assertEqual(parsed["go"], out["go"])
        self.assertEqual(parsed["safety_gb"], self.s.reserve_gb)

    def test_simple_check_refuses_what_cannot_fit(self):
        out = memory.preflight(100000, self.s)
        self.assertFalse(out["go"])
        self.assertIn("NO-GO", out["report"])

    def test_named_writer_uses_its_measured_size(self):
        out = memory.preflight("9b", self.s)
        self.assertEqual(out["need_gb"], 10.0)
        self.assertIn("9b is taken as 10 GB", out["report"])

    def test_nonsense_is_refused(self):
        self.assertFalse(memory.preflight("banana", self.s)["go"])

    def test_named_governor_that_is_missing_fails_closed(self):
        out = memory.preflight(1, self.s, governor="/nonexistent/governor.py")
        self.assertFalse(out["go"])
        self.assertFalse(out["answered"])
        self.assertEqual(out["method"], "governor")


class Lanes(unittest.TestCase):
    def setUp(self):
        self.addCleanup(clean_environment().stop)

    def test_empty_path_is_never_present(self):
        self.assertFalse(lanes.present({"path": "", "for": "x", "kind": "tool"}))
        self.assertFalse(lanes.present(""))

    def test_missing_gives_plain_words(self):
        s = settings.load(Path(tempfile.mkdtemp()) / "none.toml", fresh=True)
        self.assertIn("ltx-2-mlx", lanes.why_off("video", s))
        self.assertTrue(lanes.why_off("video", s).startswith("Switched off on this machine. Missing:"))
        self.assertEqual(lanes.why_off("animation", s) if Path(s.tool("ffmpeg")).exists() else "", "")


if __name__ == "__main__":
    unittest.main()
