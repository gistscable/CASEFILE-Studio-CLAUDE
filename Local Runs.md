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

### If renders are slow in Docker on a Mac

On an Apple-silicon Mac (M1–M4) the image must be the **arm64** build. An amd64 (Intel) image
still runs, but every FFmpeg instruction is translated (Rosetta or QEMU), which makes the
Export and the Re-cut several times slower. Check both of these:

```bash
docker image inspect casefile-studio --format '{{.Os}}/{{.Architecture}}'   # want: linux/arm64
docker run --rm --entrypoint sh casefile-studio -c 'uname -m; nproc'      # want: aarch64, and your CPU count
```

If it says `amd64` / `x86_64`, rebuild it for the Mac (and check `echo $DOCKER_DEFAULT_PLATFORM`
is empty, since that variable forces amd64):

```bash
docker build --platform linux/arm64 -t casefile-studio .
```

If `nproc` is small (1–2), raise the CPUs in Docker Desktop → Settings → Resources. Since
v0.4.48 the export renders several scenes at once (about one per two CPUs, at most 6;
`-e CASEFILE_RENDER_JOBS=1` brings back one at a time), and the progress message says when the app
is running as translated Intel code or with only 1–2 CPUs.
