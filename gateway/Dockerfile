FROM python:3.12-slim

WORKDIR /app

# Zależności systemowe wymagane przez spaCy i Presidio
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modele językowe spaCy — małe wersje do prototypu
RUN python -m spacy download pl_core_news_sm
RUN python -m spacy download en_core_web_sm

COPY . .

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
