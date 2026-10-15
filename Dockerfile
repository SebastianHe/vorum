FROM python:3.12-slim
LABEL org.opencontainers.image.title="Vorum" \
      org.opencontainers.image.source="https://github.com/SebastianHe/vorum" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VORUM_DATA=/app/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home vorum
COPY vorum ./vorum
COPY docs ./docs
COPY LICENSE ./LICENSE
RUN mkdir -p /app/data && chown vorum:vorum /app/data
USER vorum
VOLUME /app/data
EXPOSE 8000
CMD ["gunicorn", "--preload", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "60", "vorum:create_app()"]
