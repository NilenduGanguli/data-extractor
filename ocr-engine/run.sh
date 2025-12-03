#!/bin/bash

# Build the Docker image
echo "Building Docker image..."
docker build -t ocr-engine .

# Run the Docker container
echo "Running OCR Engine on port 8000..."
docker run -p 8000:8000 ocr-engine
