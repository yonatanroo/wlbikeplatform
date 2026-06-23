FROM python:3.11

WORKDIR /app

# Packages apart — gecached zolang requirements.txt niet verandert
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code
COPY . .

# app.py leest zelf PORT uit de environment
CMD ["python", "app.py"]
