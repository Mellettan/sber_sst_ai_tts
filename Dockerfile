FROM python:3.11-slim

WORKDIR /vocode_project

RUN apt-get update && apt-get install -y \
    gcc \
    portaudio19-dev \
    libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install poetry

COPY pyproject.toml poetry.lock* ./

RUN poetry config virtualenvs.create false \
    && poetry install

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.web.server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]