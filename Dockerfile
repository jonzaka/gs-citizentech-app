# Etapa 1: instala as dependencias em uma pasta separada.
FROM python:3.12-slim AS build
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Etapa 2: imagem final, so com o necessario para rodar.
FROM python:3.12-slim
ARG GIT_SHA=dev
LABEL org.opencontainers.image.source="https://github.com/jonzaka/gs-citizentech-app"
ENV APP_VERSION=${GIT_SHA} \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir /data \
    && chown app /data

COPY --from=build /install /usr/local
WORKDIR /srv
COPY app ./app

USER 10001
EXPOSE 8000
VOLUME /data

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
