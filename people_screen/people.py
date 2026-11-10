#!/usr/bin/env python3
"""Who may sign in to the people screen. Run on the Studio itself; there is no way to do this from the screen.

  people.py add "Name"      makes a passcode for that person and prints it once. Give it to them; it is not kept.
  people.py list            who holds a passcode, and how many devices each is signed in on.
  people.py remove "Name"   takes the passcode away and signs that person out everywhere.

The screen in use decides the state folder: set PS_STATE_DIR the same way its start script does (the live
screen's launchd job leaves it unset, so the default folder inside people_screen/ is the live one; the test
screen on 8103 uses neovak-studio/state/people_screen). A running screen reads the file on every sign in,
so nothing needs restarting.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import auth  # noqa: E402

USAGE = __doc__.strip()


def main(argv):
    people = auth.People()
    sessions = auth.Sessions()
    if len(argv) == 2 and argv[0] == "add":
        try:
            person, code = people.add(argv[1])
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
        print(f"Passcode for {person['name']}:  {code}")
        print("Shown once and not kept. They type it on the sign-in page; dashes and capitals do not matter.")
        return 0
    if argv == ["list"]:
        rows = people.listing()
        if not rows:
            print(f"Nobody holds a passcode yet ({people.path}).")
            return 0
        for p in rows:
            n = sessions.count_for(p["id"])
            print(f"{p['name']:<{auth.MAX_NAME}}  added {p.get('added') or '?'}  signed in on {n} device{'s' if n != 1 else ''}")
        return 0
    if len(argv) == 2 and argv[0] == "remove":
        person = people.remove(argv[1])
        if person is None:
            print(f"There is no passcode for {argv[1]}.", file=sys.stderr)
            return 1
        dropped = sessions.drop_person(person["id"])
        print(f"Removed {person['name']}'s passcode and signed them out on {dropped} device{'s' if dropped != 1 else ''}.")
        return 0
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
