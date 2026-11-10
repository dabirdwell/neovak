"""The screen's front door: no session, no route; wrong passcodes are limited; a right one signs in; the cookie
survives a restart; sign out works; people.py adds, lists and removes. Run from this folder:
  ../venv/bin/python3 -m unittest test_sign_in
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="neovak_signin_"))
(TMP / "out").mkdir()
(TMP / "env").write_text("NEOVAK_TOKEN=test-token-for-the-unit-tests\n")
os.environ.update(PS_STATE_DIR=str(TMP / "state"), PS_OUTPUT_DIR=str(TMP / "out"), PS_BACKEND="http://127.0.0.1:9",
                  PS_HELPER="http://127.0.0.1:9", PS_GOVERNOR=str(TMP / "gov.py"), NEOVAK_ENV_FILE=str(TMP / "env"),
                  PS_EXTRA_HOSTS="studio.tail-example.ts.net")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import auth  # noqa: E402
import app as screen  # noqa: E402
import core  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

screen.WRONG_PASSCODE_PAUSE = 0
JSON = {"Content-Type": "application/json"}
HERE = Path(__file__).resolve().parent


def fresh_client(base="http://127.0.0.1:8103"):
    return TestClient(screen.app, base_url=base, raise_server_exceptions=False)


def cookie_header(response):
    return response.headers.get("set-cookie", "")


class Door(unittest.TestCase):
    def setUp(self):
        screen.ATTEMPTS = auth.Attempts()

    def test_no_session_is_refused_on_every_route(self):
        c = fresh_client()
        seen = 0
        for route in screen.app.routes:
            path = re.sub(r"\{[^}]+\}", "x", route.path)
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                r = c.request(method, path, headers=JSON if method in ("POST", "DELETE") else {}, content="{}" if method == "POST" else None)
                seen += 1
                if path == "/api/signin":
                    self.assertEqual(r.json()["error"], "That passcode did not match.", "the sign-in call itself must be open")
                    continue
                self.assertEqual(r.status_code, 401, f"{method} {path} answered {r.status_code}")
                if path == "/" and method == "GET":
                    self.assertIn("text/html", r.headers["content-type"])
                    self.assertIn("Sign in", r.text)
                    self.assertTrue("No passcode has been made yet" in r.text or "Passcodes are made on the Mac that runs NeoVak" in r.text)
                    self.assertIn("nonce-", r.headers["content-security-policy"])
                else:
                    self.assertEqual(r.json()["error"], "Please sign in first.")
                self.assertEqual(r.headers.get("cache-control"), "no-store")
        self.assertGreater(seen, 30)
        for path in ("/media/good.png", "/thumb/good.png", "/ui/studio.css", "/starters/manifest.json", "/peek/x", "/api/gallery"):
            self.assertEqual(c.get(path).status_code, 401, path)

    def test_wrong_passcodes_are_limited_per_address(self):
        c = fresh_client()
        for i in range(auth.TRIES_PER_ADDRESS):
            r = c.post("/api/signin", json={"code": "nope-nope-nope"}, headers=JSON)
            self.assertEqual(r.status_code, 401, i)
            self.assertEqual(r.json()["error"], "That passcode did not match.")
        r = c.post("/api/signin", json={"code": "nope-nope-nope"}, headers=JSON)
        self.assertEqual(r.status_code, 429)
        self.assertIn("Too many tries", r.json()["error"])
        self.assertGreater(r.json()["wait"], 0)
        # a right passcode is not accepted either while the address is held
        person, code = screen.PEOPLE.add("Held")
        try:
            self.assertEqual(c.post("/api/signin", json={"code": code}, headers=JSON).status_code, 429)
            # another address is not held, and the wait is bounded by the window
            self.assertEqual(screen.ATTEMPTS.wait_seconds("somewhere else"), 0)
            self.assertLessEqual(screen.ATTEMPTS.wait_seconds("testclient"), auth.WINDOW_SECONDS + 1)
            # behind Tailscale Serve the forwarded address counts; from a real address the header is ignored
            served = {"host": "studio.tail-example.ts.net"}
            self.assertEqual(auth.address_of(dict(served, **{"x-forwarded-for": "100.64.0.9, 127.0.0.1"}), "127.0.0.1"), "100.64.0.9")
            # a forwarder adds the address it saw at the end, so what the client wrote before it is ignored
            self.assertEqual(auth.address_of(dict(served, **{"x-forwarded-for": "10.9.0.1, 100.64.0.9"}), "127.0.0.1"), "100.64.0.9")
            # straight to the loopback address there is no forwarder, so the header is ignored
            self.assertEqual(auth.address_of({"host": "127.0.0.1:8103", "x-forwarded-for": "10.9.0.1"}, "127.0.0.1"), "127.0.0.1")
            self.assertEqual(auth.address_of({"x-forwarded-for": "1.2.3.4"}, "100.64.1.1"), "100.64.1.1")
            self.assertEqual(auth.address_of({}, "127.0.0.1"), "127.0.0.1")
            # once the count for everyone is reached, everyone gets one try a minute, not a 15 minute lock
            a = auth.Attempts()
            for i in range(auth.TRIES_IN_ALL):
                a.failed(f"10.0.0.{i}")
            wait = a.wait_seconds("10.9.9.9")
            self.assertGreater(wait, 0)
            self.assertLessEqual(wait, auth.SHARED_GAP_SECONDS + 1)
        finally:
            screen.PEOPLE.remove("Held")

    def test_right_passcode_signs_in_and_the_cookie_is_strict(self):
        person, code = screen.PEOPLE.add("Ada Lovelace")
        try:
            c = fresh_client()
            typed = code.upper().replace("-", " ")  # capitals and spaces are forgiven
            r = c.post("/api/signin", json={"code": typed}, headers=JSON)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json(), {"name": "Ada Lovelace"})
            ck = cookie_header(r)
            self.assertIn(auth.COOKIE + "=", ck)
            self.assertIn("HttpOnly", ck)
            self.assertIn("SameSite=strict", ck)
            self.assertIn("Path=/", ck)
            self.assertIn(f"Max-Age={30 * 86400}", ck)
            self.assertNotIn("Secure", ck, "plain http on the tailnet gets no Secure flag, or the cookie would never come back")
            self.assertEqual(c.get("/").status_code, 200)
            self.assertIn("/ui/base.js", c.get("/").text)
            st = c.get("/api/status")
            self.assertEqual(st.status_code, 200)
            self.assertEqual(st.json()["person"], "Ada Lovelace")
            self.assertEqual(c.get("/ui/studio.css").status_code, 200)
            self.assertEqual(c.get("/api/gallery").status_code, 200)
            self.assertNotIn(auth.normalize(code), json.dumps(json.loads(auth.PEOPLE_FILE.read_text())), "the passcode itself is never stored")
        finally:
            screen.PEOPLE.remove("Ada Lovelace")

    def test_secure_flag_follows_https(self):
        person, code = screen.PEOPLE.add("Over Https")
        try:
            r = fresh_client().post("/api/signin", json={"code": code}, headers=dict(JSON, **{"X-Forwarded-Proto": "https"}))
            self.assertEqual(r.status_code, 200)
            self.assertIn("Secure", cookie_header(r))
            if "studio.tail-example.ts.net" in screen.ALLOWED:  # not when another test module imported the app first, without PS_EXTRA_HOSTS
                r = fresh_client("https://studio.tail-example.ts.net").post("/api/signin", json={"code": code}, headers=JSON)
                self.assertEqual(r.status_code, 200, "the Tailscale Serve name is allowed through PS_EXTRA_HOSTS")
                self.assertIn("Secure", cookie_header(r))
            self.assertEqual(fresh_client("http://evil.example").post("/api/signin", json={"code": code}, headers=JSON).status_code, 400)
        finally:
            screen.PEOPLE.remove("Over Https")

    def test_session_survives_a_restart_of_the_screen(self):
        person, code = screen.PEOPLE.add("Restart")
        try:
            c = fresh_client()
            self.assertEqual(c.post("/api/signin", json={"code": code}, headers=JSON).status_code, 200)
            token = c.cookies.get(auth.COOKIE)
            self.assertTrue(token)
            screen.SESSIONS = auth.Sessions()  # what a restart does: read the file again from nothing
            self.assertEqual(screen.SESSIONS.person_for(token)["name"], "Restart")
            self.assertEqual(c.get("/api/status").status_code, 200)
        finally:
            screen.PEOPLE.remove("Restart")

    def test_sign_out_ends_the_session(self):
        person, code = screen.PEOPLE.add("Leaving")
        try:
            c = fresh_client()
            self.assertEqual(c.post("/api/signin", json={"code": code}, headers=JSON).status_code, 200)
            token = c.cookies.get(auth.COOKIE)
            self.assertEqual(c.post("/api/signout", json={}, headers=dict(JSON, Origin="http://evil.example")).status_code, 400)
            r = c.post("/api/signout", json={}, headers=JSON)
            self.assertEqual(r.status_code, 200)
            self.assertIn("Max-Age=0", cookie_header(r))
            again = fresh_client()
            again.cookies.set(auth.COOKIE, token)
            self.assertEqual(again.get("/api/status").status_code, 401, "a kept copy of the old cookie is dead too")
            self.assertIsNone(auth.Sessions().person_for(token))
        finally:
            screen.PEOPLE.remove("Leaving")

    def test_removing_a_person_signs_them_out_at_once(self):
        person, code = screen.PEOPLE.add("Gone")
        c = fresh_client()
        self.assertEqual(c.post("/api/signin", json={"code": code}, headers=JSON).status_code, 200)
        self.assertEqual(c.get("/api/status").status_code, 200)
        # what people.py remove does, in another process, while the screen keeps running
        cli_people, cli_sessions = auth.People(), auth.Sessions()
        gone = cli_people.remove("Gone")
        self.assertEqual(cli_sessions.drop_person(gone["id"]), 1)
        self.assertEqual(c.get("/api/status").status_code, 401)
        self.assertEqual(c.post("/api/signin", json={"code": code}, headers=JSON).status_code, 401)

    def test_sign_in_page_shows_the_app_style_and_no_app_code(self):
        r = fresh_client().get("/")
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("/ui/", r.text, "nothing of the app is served before sign-in")
        self.assertIn("Open the studio", r.text)
        self.assertIn("prefers-reduced-motion", r.text)
        self.assertNotIn(chr(0x2014), r.text)  # no long dash anywhere on the page


class CommandLine(unittest.TestCase):
    def run_people(self, *args):
        env = dict(os.environ, PS_STATE_DIR=str(TMP / "cli_state"))
        return subprocess.run([sys.executable, str(HERE / "people.py"), *args], capture_output=True, text=True, env=env)

    def test_add_list_remove(self):
        self.assertEqual(self.run_people("list").stdout.strip(), f"Nobody holds a passcode yet ({TMP / 'cli_state' / 'people.json'}).")
        r = self.run_people("add", "Grace Hopper")
        self.assertEqual(r.returncode, 0, r.stderr)
        m = re.search(r"Passcode for Grace Hopper:\s+([a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})", r.stdout)
        self.assertTrue(m, r.stdout)
        code = m.group(1)
        self.assertFalse(set(code) & set("ilo01"), "no letters that are misread when read aloud")
        self.assertIn("Shown once", r.stdout)
        self.assertEqual(self.run_people("add", "grace hopper").returncode, 1, "one passcode per name")
        listing = self.run_people("list").stdout
        self.assertIn("Grace Hopper", listing)
        self.assertIn("signed in on 0 devices", listing)
        stored = (TMP / "cli_state" / "people.json").read_text()
        self.assertNotIn(code.replace("-", ""), stored)
        self.assertEqual(oct((TMP / "cli_state" / "people.json").stat().st_mode)[-3:], "600")
        people = auth.People(TMP / "cli_state" / "people.json")
        self.assertEqual(people.check(code)["name"], "Grace Hopper")
        self.assertIsNone(people.check(code[:-1] + ("a" if code[-1] != "a" else "b")))
        r = self.run_people("remove", "Grace Hopper")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Removed Grace Hopper's passcode", r.stdout)
        self.assertEqual(self.run_people("remove", "Grace Hopper").returncode, 1)
        self.assertEqual(self.run_people().returncode, 2)


class EngineToken(unittest.TestCase):
    def test_screen_sends_the_token_the_engine_reads(self):
        from neovak_queue import secret
        secret.ENV_FILE = TMP / "env"  # when another test module imported the code first, it read the default path
        req = core.backend_request("/api/jobs?limit=1")
        self.assertEqual(req.get_header("Authorization"), "Bearer test-token-for-the-unit-tests")
        req = core.backend_request("/api/jobs", {"lane": "image"})
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Authorization"), "Bearer test-token-for-the-unit-tests")
        self.assertEqual(secret.presented({"authorization": "Bearer abc"}), "abc")
        self.assertEqual(secret.presented({"x-neovak-token": "abc"}), "abc")
        self.assertIsNone(secret.presented({}))
        self.assertTrue(secret.matches("abc", "abc"))
        self.assertFalse(secret.matches("abd", "abc"))
        self.assertFalse(secret.matches(None, "abc"))
        self.assertFalse(secret.matches("abc", None))

    def test_token_file_forms(self):
        from neovak_queue import secret
        f = TMP / "env2"
        f.write_text("# a note\nHF_TOKEN=not_a_key\nexport NEOVAK_TOKEN=\"quoted value\"\n")
        self.assertEqual(secret._from_file(f), "quoted value")
        f.write_text("HF_TOKEN=x\n")
        self.assertIsNone(secret._from_file(f))
        self.assertIsNone(secret._from_file(TMP / "missing"))
        self.assertEqual(secret.auth_headers("t"), {"Authorization": "Bearer t"})
        self.assertEqual(secret.auth_headers(""), {})


if __name__ == "__main__":
    unittest.main()
