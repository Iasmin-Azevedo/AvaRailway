FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Em produção o bind costuma ser 0.0.0.0 dentro do container; o acesso público fica no Nginx do host
# (proxy para 127.0.0.1:8000). Para desenvolvimento local, o mesmo comando serve.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
