import os
import random
import string
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
import redis

app = FastAPI(title="K8s Practice URL Shortener")

# Брем настройки из ENV (это пригодится для ConfigMap/Secret)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# Подключение к Redis
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)

class URLRequest(BaseModel):
    url: HttpUrl

def generate_code():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=6))

@app.post("/shorten")
def shorten_url(data: URLRequest):
    code = generate_code()
    # Сохраняем в Redis
    r.set(code, str(data.url))
    return {"short_url": f"http://localhost:8000/{code}"}

@app.get("/heavy")
def heavy():
    total = sum(i * i for i in range(1, 20_000_000))
    return {"result": total}

@app.get("/healthz")
def health_check():
    try:
        r.ping()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Redis unavailable: {e}"
        )

@app.get("/{code}")
def redirect_to_url(code: str):
    original_url = r.get(code)
    if not original_url:
        raise HTTPException(status_code=404, detail="URL not found")
    return {"redirect_to": original_url}
