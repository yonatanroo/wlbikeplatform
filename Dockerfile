FROM python:3.11-slim

WORKDIR /app

# Installeer packages apart — Railway cached deze laag zolang requirements.txt niet verandert
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopieer de rest van de code
COPY . .

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
