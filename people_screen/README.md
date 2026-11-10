# NeoVak studio screen

The screen is the web page a person uses: one place for pictures, video, voice, music, animation, writing, editing and recipes, over the engine's job queue. It runs as its own process on port 8102 and talks to the engine on port 8100.

Open it at http://127.0.0.1:8102 on the Mac that runs it. To reach it from another device on a private network, add that address under [hosts] screen in the settings file (see neovak_queue/settings.py); it listens on nothing else.

## Sign in

Every route needs a signed-in session, whatever address the request comes from (a tunnel or a private network forwarder makes a remote request look local, so the address is never trusted). Each person has their own passcode, made and removed only on the Mac that runs the screen:

- people_screen/people.py add "Name" prints a passcode once; list shows who has one and on how many devices they are signed in; remove "Name" takes it away and signs them out everywhere. Set PS_STATE_DIR the way the screen's start script does (unset for the live screen; studio_test/people.sh does it for the test screen on 8103).
- Passcodes are stored salted and hashed (scrypt) in the state folder's people.json; sessions last 30 days, survive a restart, and live in sessions.json as hashes. The cookie is HttpOnly, SameSite Strict, and Secure when the request came over https.
- Wrong passcodes are limited: 8 from one address, 60 from everywhere, in 15 minutes.
- PS_EXTRA_HOSTS (comma separated) lets the screen answer to another name, such as the name a private network forwarder gives this Mac. The addresses it binds come from [hosts] screen in the settings file.
- The screen sends the engine's access token (NEOVAK_TOKEN in ~/.config/neovak/env, see neovak_queue/secret.py) on every call to the engine. With no token in that file the engine stays open to anyone who can reach its port, and its /health says so.

## Start and stop

- people_screen/start.sh and stop.sh start and stop it. Logs: state/logs/server.log. Why a job failed: state/logs/failures.log.
- Tests (no models, temporary folders only): venv/bin/python3 people_screen/test_people_screen.py, and the rest of tests/.

## How it is put together

- app.py: the web routes. core.py: lanes, the memory check, the nightly window, the gallery, the queue client. studio.py: projects, the model shelf and installs, starters, and the small derived files (subject layer, waveforms, film strips). install_runner.py: one download, in its own process group.
- index.html is the skeleton. ui/ holds studio.css and the page's script in parts (base, fx, stage, inspector, starters, library, timeline, models, boot). Scripts load only from this server. A strict content security policy keeps the page from loading or sending anything anywhere else. ui/ and starters/ are served by bare file name only.
- Every lane is a job on the engine's queue (POST /api/jobs on the engine): Picture, Video, Voice, Music, Animate, Writing, Edit, Recipes, and the Film joined from a timeline. The queue runs one thing at a time, asks the memory check before every model, and holds model work during the nightly window if the settings name one. The screen holds up to 12 things in line.
- Every folder, outside tool and address comes from the settings file. What each lane needs from the machine is listed once in neovak_queue/lanes.py; a lane with something missing is switched off on the page with that reason, and neovak_queue/doctor.py prints the same list.
- Everything a job makes gets a sidecar (.json beside it) and is recorded in the project that was open when it was asked for.
- Models offered for download are a fixed list in studio.py. Each was read for its licence, is under 10 GB, and has run on a Mac. The download is made without an account token and goes to the [models] added folder from the settings file.
- The screen's own records are in the [folders] screen_state folder (records.json, projects.json, thumbnails, derived files). Starter pictures and sounds are real outputs from local models, in starters/.
