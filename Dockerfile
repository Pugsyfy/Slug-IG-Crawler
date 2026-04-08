FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

# ------------------------------------------------------
# System deps (Chrome runtime)
# ------------------------------------------------------
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxshmfence1 \
    libu2f-udev \
    libvulkan1 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------
# Chrome for Testing (VERSION LOCKED)
# ------------------------------------------------------
WORKDIR /opt

RUN wget -q https://storage.googleapis.com/chrome-for-testing-public/143.0.7499.170/linux64/chrome-linux64.zip \
    && wget -q https://storage.googleapis.com/chrome-for-testing-public/143.0.7499.170/linux64/chromedriver-linux64.zip \
    && unzip chrome-linux64.zip \
    && unzip chromedriver-linux64.zip \
    && rm chrome-linux64.zip chromedriver-linux64.zip \
    && chmod +x /opt/chrome-linux64/chrome \
    && chmod +x /opt/chromedriver-linux64/chromedriver

# ------------------------------------------------------
# Canonical, VERIFIED paths (from your find output)
# ------------------------------------------------------
ENV CHROME_BIN=/opt/chrome-linux64/chrome \
    CHROMEDRIVER_BIN=/opt/chromedriver-linux64/chromedriver

# ------------------------------------------------------
# HARD ASSERT: Chrome & Driver MAJOR versions must match
# ------------------------------------------------------
RUN CHROME_VERSION=$($CHROME_BIN --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+') && \
    DRIVER_VERSION=$($CHROMEDRIVER_BIN --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+') && \
    echo "Chrome:      $CHROME_VERSION" && \
    echo "Chromedriver:$DRIVER_VERSION" && \
    test "${CHROME_VERSION%%.*}" = "${DRIVER_VERSION%%.*}"

# ------------------------------------------------------
# App (dependencies from pyproject.toml)
# ------------------------------------------------------
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --upgrade pip \
    && pip install --no-cache-dir ".[video]"

COPY . .

CMD ["Slug-Ig-Crawler", "--config", "config.toml"]
