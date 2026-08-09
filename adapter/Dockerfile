FROM python:3.12-slim-bookworm

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      baresip-core \
      baresip-gstreamer \
      baresip-x11 \
      bluez \
      ffmpeg \
      gstreamer1.0-libav \
      gstreamer1.0-plugins-good \
      pulseaudio \
      pulseaudio-module-bluetooth \
      pulseaudio-utils \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir sendspin==7.5.0

WORKDIR /app
COPY adapter.py ./
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin intercom \
 && mkdir -p /captures /run/intercom \
 && chown -R intercom:intercom /captures /run/intercom /app
USER intercom:intercom
ENV XDG_RUNTIME_DIR=/run/intercom
EXPOSE 8080
CMD ["python3", "/app/adapter.py"]
