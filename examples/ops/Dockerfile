# Dockerfile for Astro Bot example
#
# Build (from repo root, after make dist):
#   copy dist\kstlib-*.whl examples\ops\
#   docker build -t astro-bot examples/ops/
#
# Run standalone:
#   docker run -it --name astro astro-bot
#
# Run via kstlib:
#   python run_container.py

FROM python:3.10-slim

LABEL maintainer="kstlib"
LABEL description="Astro Bot - Simple persistent bot demo"

WORKDIR /app

# Copy and install local kstlib wheel (built with: make dist)
COPY kstlib-*.whl ./
RUN pip install --no-cache-dir kstlib-*.whl && rm -f kstlib-*.whl

# Copy the bot script
COPY astro_bot.py .

# Run the bot (-u for unbuffered output)
CMD ["python", "-u", "astro_bot.py"]
