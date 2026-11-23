docker build -t casefile-studio . \&\& docker run --rm -p 127.0.0.1:8000:8000 -v casefile-data:/app/data --entrypoint python casefile-studio -m uvicorn app:app --host 0.0.0.0 --port 8000
