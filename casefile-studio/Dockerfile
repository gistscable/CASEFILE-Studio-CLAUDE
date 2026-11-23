FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core gosu && rm -rf /var/lib/apt/lists/*
# v0.4.19 "Fetch from guide": yt-dlp needs a JavaScript runtime for YouTube.
# Deno (>= 2.3) is the one yt-dlp recommends and enables by default; Debian's
# Node is too old. The official deno:bin image is just the binary.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno
RUN deno --version
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && yt-dlp --version
# v0.4.21 "Make the timing from the audio": Whisper on this computer. Optional:
# if it cannot be installed on this machine the build still succeeds and the
# app says so; CapCut SRT/JSON upload keeps working.
RUN pip install --no-cache-dir "faster-whisper>=1.1" \
    && python -c "import faster_whisper, ctranslate2; print('Whisper ready:', faster_whisper.__version__, 'ctranslate2', ctranslate2.__version__)" \
    || echo "WARNING: Whisper was not installed; timing from audio is unavailable. The lines above say why."
RUN useradd --create-home --uid 10001 studio
COPY --chown=studio:studio . /app
# The entrypoint starts as root only to hand a mounted data disk (Render mounts
# it root-owned) to `studio`, then drops privileges before the server starts.
# With no mounted disk it runs as `studio` from the start.
# Keep the entrypoint executable even if the checkout loses the file mode.
RUN mkdir -p /app/data && chown -R studio:studio /app \
    && chmod 755 /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
# Bind to $PORT (Render's routing port, default 10000). One worker only: the app
# keeps in-flight jobs and AI sessions in process memory.
CMD ["sh", "-c", "exec python -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips=*"]
EXPOSE 10000
