# Local runs

## Without Docker (macOS) — recommended for day-to-day use

One-time setup (Homebrew):

```bash
brew install python@3.12 ffmpeg
cd casefile-studio
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Check FFmpeg has subtitle support (captions need it): `ffmpeg -hide_banner -filters | grep subtitles`
should print a line. Fonts are bundled with the app, so nothing else is needed. The web
interface is prebuilt; Node is only needed if you change `web/src/`.

Start it (each time):

```bash
cd casefile-studio
PATH="$PWD/.venv/bin:$PATH" ./run.sh              # http://127.0.0.1:8000
PORT=8001 PATH="$PWD/.venv/bin:$PATH" ./run.sh    # another port
```

Stop with Ctrl+C. After `git pull`, just stop and start it again; there is no build step.
Data lives in `casefile-studio/data/`.

### Bring over projects made in Docker (once)

Docker kept its data in the `casefile-data` volume, which the native app cannot see. Copy it
into `casefile-studio/data/` (stored file paths are relative to that folder, so it must go
there, not to a separate folder):

```bash
cd casefile-studio
cp -a data ../data-backup-before-docker-copy        # safety copy of the in-repo data
docker run --rm -v casefile-data:/app/data -v "$PWD/data":/out --entrypoint sh casefile-studio \
  -c 'cp -a /app/data/. /out/'
```

Then start the app as above. Uploaded media (`data/media/`) is git-ignored; changed project
files under `data/projects/` will show up in `git status` — commit them or not, as you prefer.

## With Docker

```bash
docker build -t casefile-studio . && docker run --rm -p 127.0.0.1:8000:8000 -v casefile-data:/app/data --entrypoint python casefile-studio -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Run from `casefile-studio/`. The image must be rebuilt after every code change.
