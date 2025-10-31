# Base image: Debian slim with ARM support for Raspberry Pi
FROM python:3.13-slim-bullseye

# Non-root user
RUN useradd -ms /bin/bash appuser

# Install FFmpeg and minimal dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
        libavcodec-extra \
        && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application code
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Fix ownership
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose Flask port
EXPOSE 5000

# Optional: lightweight healthcheck for Docker
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://localhost:5000/ || exit 1

# Run Flask app
CMD ["python", "app.py"]
