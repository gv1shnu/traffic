FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 OMP_NUM_THREADS=2 MPLCONFIGDIR=/tmp/matplotlib YOLO_CONFIG_DIR=/tmp/ultralytics
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY apps/__init__.py apps/__init__.py
COPY packages/ packages/
COPY fixtures/ fixtures/
# CPU wheels by default; pass a CUDA index (e.g. https://download.pytorch.org/whl/cu128) for GPU builds.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --index-url "$TORCH_INDEX_URL" torch torchvision && pip install '.[vision]'
COPY . .
RUN useradd --uid 10001 --create-home traffic && mkdir -p /data /models && chown -R traffic:traffic /app /data /models
USER traffic
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
