FROM python:3.11-slim

WORKDIR /app

# 安装运行时依赖
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目
COPY server/app/ ./app/
COPY client/ ./client/
COPY kpak/ ./kpak/

# 创建数据目录
RUN mkdir -p /app/data/chroma /app/data/feedback_logs /app/data/kpak

ENV KAFED_DATA_DIR=/app/data
ENV KAFED_HOST=0.0.0.0
ENV KAFED_PORT=8765

EXPOSE 8765

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
