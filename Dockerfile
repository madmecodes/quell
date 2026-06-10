# Quell operator dashboard (runs the 6-agent pipeline).
# Python runs the dashboard + agents. Node is included so the live read path can
# route DQL through the OFFICIAL Dynatrace MCP server (@dynatrace-oss/dynatrace-mcp-server)
# when QUELL_USE_MCP=true. Mock mode still needs only the Python standard library.
FROM python:3.12-slim
WORKDIR /app

# Node.js 20 + the official Dynatrace MCP server, pre-installed so `npx` is
# instant at runtime (no cold download on first DQL). nodejs ships npm/npx.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @dynatrace-oss/dynatrace-mcp-server \
    && apt-get purge -y gnupg \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY agents/ ./agents/
COPY dashboard/ ./dashboard/
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
EXPOSE 8080
CMD ["python", "dashboard/server.py"]
