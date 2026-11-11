# Same Python minor version the test suite was run with.
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser
EXPOSE 8010
# Railway uses pre-deploy migrations and RUN_MIGRATIONS_ON_START=false.
# Standalone/Compose keeps its existing migrate-on-start convenience.
CMD ["sh", "start.sh"]
