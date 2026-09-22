FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# 1. Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# 2. Set up working directory and user for Hugging Face Spaces (UID 1000)
WORKDIR /app
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

# 3. Copy dependencies and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 4. Install Playwright browser binaries and dependencies as root
RUN playwright install --with-deps chromium

# 5. Copy project files and assign ownership to user 1000
COPY . .
RUN chown -R user:user /app /home/user

# Switch to non-root user
USER user

# 6. Expose default Hugging Face Spaces port (7860)
EXPOSE 7860

# 7. Start Streamlit on port 7860
CMD ["streamlit", "run", "web_app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.fileWatcherType=none"]