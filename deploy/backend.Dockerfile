FROM python:3.12-slim

WORKDIR /app

COPY backend/pyproject.toml ./backend/
COPY backend/orbitlink ./backend/orbitlink
COPY data ./data
COPY docs/reference_geometry.py ./docs/reference_geometry.py

RUN pip install --no-cache-dir ./backend

ENV PYTHONUNBUFFERED=1
ENV ORBITLINK_DB=sqlite:////app/state/orbitlink.db
RUN mkdir -p /app/state

EXPOSE 8000
CMD ["uvicorn", "orbitlink.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
