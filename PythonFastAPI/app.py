import os
import json
import random
import string
import logging
from fastapi import FastAPI, HTTPException, status
import redis
from prometheus_fastapi_instrumentator import Instrumentator

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("url_shortener")

app = FastAPI()

#Prometheus
Instrumentator().instrument(app).expose(app)

# Чтение переменных окружения для подключения к Redis
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# Инициализация клиента Redis
r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    decode_responses=True
)

# Дефолтные настройки на случай, если файл конфигурации отсутствует
config = {
    "max_link_length": 2048,
    "environment": "development"
}

CONFIG_FILE_PATH = "/app/config/config.json"

# Попытка прочитать конфигурацию из ConfigMap (примонтированного как файл)
if os.path.exists(CONFIG_FILE_PATH):
    try:
        with open(CONFIG_FILE_PATH, "r") as f:
            config.update(json.load(f))
        logger.info(f"Configuration loaded successfully from {CONFIG_FILE_PATH}")
    except Exception as e:
        logger.error(f"Failed to parse config file: {e}. Using defaults.")
else:
    logger.warning(f"Config file not found at {CONFIG_FILE_PATH}. Using default parameters.")

logger.info(f"Starting API in {config['environment'].upper()} mode")


def generate_short_code(length=6):
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


# 1. Умная проба здоровья (Readiness/Liveness)
@app.get("/healthz")
def health_check():
    try:
        # Проверяем реальное соединение с Redis
        if r.ping():
            return {"status": "ok", "environment": config["environment"]}
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
        logger.error(f"Healthcheck failed: cannot connect to Redis. Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection unavailable"
        )
    except Exception as e:
        logger.error(f"Unknown healthcheck error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


# 2. Ресурсоемкий эндпоинт для теста HPA
@app.get("/heavy")
def heavy_load():
    # Нагружаем CPU: вычисление суммы квадратов большого диапазона чисел
    result = sum(i * i for i in range(1, 5_000_000))
    return {"status": "heavy_calculation_done", "result": result}


# 3. Эндпоинт для создания коротких ссылок с проверкой лимита длины
@app.post("/shorten")
def shorten_url(url: str):
    # Валидация длины ссылки на основе файла конфигурации
    max_length = config.get("max_link_length", 2048)
    if len(url) > max_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL length exceeds the maximum limit of {max_length} characters."
        )

    code = generate_short_code()
    
    try:
        # Сохраняем в Redis (оригинальный URL по ключу короткого кода)
        r.set(code, url)
        return {"short_url": f"http://url-shortener.local/{code}"}
    except Exception as e:
        logger.error(f"Failed to write to Redis: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save URL"
        )


# 4. Динамический роут для редиректа (должен быть в самом низу списка роутов!)
@app.get("/{code}")
def redirect_to_url(code: str):
    try:
        original_url = r.get(code)
        if original_url:
            return {"redirect_to": original_url}
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="URL not found"
        )
    except redis.exceptions.RedisError as e:
        logger.error(f"Redis error during lookup: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error"
        )