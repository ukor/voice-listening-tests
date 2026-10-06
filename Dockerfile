# Use the official lightweight Python image.
# Using 3.11 to match the PYTHON_VERSION in your render.yaml
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for some Python packages (if any)
# RUN apt-get update && apt-get install -y \
#     build-essential \
#     && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install dependencies using uv.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy the rest of the application code
COPY . .

# Expose the default Streamlit port (Render will override the PORT environment variable)
EXPOSE 8501

# Run the Streamlit application
# We use the PORT environment variable if it exists (for Render), otherwise default to 8501
CMD uv run streamlit run streamlit_app.py \
    --server.port="${PORT:-8501}" \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false \
    --server.fileWatcherType=none
