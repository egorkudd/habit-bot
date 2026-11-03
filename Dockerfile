# Образ бота: только то, что нужно для работы (раздел 7, «Место на диске»).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY habit_bot ./habit_bot

ARG VERSION=dev
LABEL org.opencontainers.image.source="https://github.com/egorkudd/habit-bot" \
      org.opencontainers.image.description="habit-bot — Telegram-бот «Дневник привычек»" \
      org.opencontainers.image.version="${VERSION}"

# Пользователь задаётся в docker-compose (uid владельца /srv/bot/data), по умолчанию — не root.
USER 1000:1000
HEALTHCHECK --interval=30s --timeout=15s --start-period=40s --retries=3 \
    CMD ["python", "-m", "habit_bot.health"]
CMD ["python", "-m", "habit_bot"]
