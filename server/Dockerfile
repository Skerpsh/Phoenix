FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends age \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY phoenix ./phoenix

ENV PYTHONUNBUFFERED=1 DATA_DIR=/data
CMD ["python", "-m", "phoenix.main"]
