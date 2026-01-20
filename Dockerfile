FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir flask beautifulsoup4 requests

# Copy application files
COPY app.py .
COPY scraper.py .
COPY scrapers.py .
COPY discovery.py .
COPY companies.json .
COPY templates/ templates/

# Create data directory
RUN mkdir -p /app/data

# Expose port
EXPOSE 5000

# Environment
ENV DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1

# Run the app
CMD ["python", "app.py"]
