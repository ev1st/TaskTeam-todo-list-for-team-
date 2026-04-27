# 🐳 TaskTeam Docker Image
FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY backend/requirements.txt ./

# Install Python dependencies with verbose output
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./backend/

# Copy frontend
COPY frontend/ ./frontend/

# Create database directory
RUN mkdir -p /app/database

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DATABASE_URL=sqlite:///./test.db
ENV SECRET_KEY=your-secret-key-change-in-production
ENV ALGORITHM=HS256
ENV ACCESS_TOKEN_EXPIRE_DAYS=7

# Expose port
EXPOSE 8000

# Run the application by default (if not overridden by docker-compose)
# Use --app-dir so that imports in `backend` that reference top-level modules like
# `from database import ...` work when the app is run from /app
CMD ["python", "-m", "uvicorn", "main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
