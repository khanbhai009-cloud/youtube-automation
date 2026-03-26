# Python 3.10 stable base image
FROM python:3.10-slim

# Step 1: System dependencies install karo (FFmpeg + ImageMagick)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    imagemagick \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Step 2: ImageMagick ki policy fix karo (MoviePy ki purani versions ke liye zaruri hai)
# Ye command "PDF" aur "URL" security restrictions ko hatati hai taaki text-to-video chal sake
RUN sed -i 's/domain="coder" rights="none" pattern="PDF"/domain="coder" rights="read|write" pattern="PDF"/' /etc/ImageMagick-6/policy.xml || true

WORKDIR /app

# Step 3: Requirements copy aur install karo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Step 4: Saara code copy karo
COPY . .

# Step 5: Hugging Face default port expose karo
EXPOSE 7860

# Step 6: Start command (Uvicorn)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
