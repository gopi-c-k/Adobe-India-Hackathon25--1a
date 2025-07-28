# Use AMD64-compatible Python image
FROM --platform=linux/amd64 python:3.10-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your code
COPY app.py .

# Create input/output dirs
RUN mkdir -p /app/input /app/output

# Command to run the script
CMD ["python", "app.py"]
