FROM python:3.12.16-slim

RUN pip install --no-cache-dir \
    faster-whisper==1.2.1 \
    ctranslate2==4.9.0 \
    numpy==2.5.5 \
    nvidia-cublas-cu12==12.9.3.13 \
    nvidia-cudnn-cu12==9.26.0.51

ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib \
    HF_HOME=/cache \
    HF_HUB_OFFLINE=1 \
    PYTHONUNBUFFERED=1

COPY server.py /app/server.py

EXPOSE 8178
CMD ["python", "/app/server.py"]
