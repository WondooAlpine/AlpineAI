FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Playwright browser and Linux OS dependencies as root
RUN playwright install --with-deps chromium

# Copy application files
COPY . .

# Render injects PORT dynamically at runtime
ENV PORT=8501
EXPOSE 8501

CMD ["sh", "-c", "streamlit run web_app.py --server.port $PORT --server.address 0.0.0.0 --server.fileWatcherType none"]
