# Quell operator dashboard (runs the 6-agent pipeline in mock mode).
# Mock mode needs only the Python standard library, so the image stays tiny.
FROM python:3.12-slim
WORKDIR /app
COPY agents/ ./agents/
COPY dashboard/ ./dashboard/
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
EXPOSE 8080
CMD ["python", "dashboard/server.py"]
