FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    RENDER_BACKEND=pillow \
    OUTPUTS_DIR=/data/outputs \
    DB_BACKEND=mysql \
    MYSQL_HOST=mysql \
    MYSQL_PORT=3306

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY sql ./sql
COPY bot.py ./

RUN useradd --create-home --uid 10001 lab \
    && mkdir -p /data/outputs \
    && chown -R lab:lab /data /app
USER lab

CMD ["python", "bot.py"]
