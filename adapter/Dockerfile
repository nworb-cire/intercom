FROM debian:bookworm-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      baresip-core \
      baresip-gstreamer \
      baresip-x11 \
      ffmpeg \
      gstreamer1.0-libav \
      gstreamer1.0-plugins-good \
      pulseaudio \
      pulseaudio-utils \
      python3 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY adapter.py ./
RUN mkdir -p /captures /run/intercom \
 && chown -R 1000:1000 /captures /run/intercom /app
USER 1000:1000
ENV XDG_RUNTIME_DIR=/run/intercom
EXPOSE 8080
CMD ["python3", "/app/adapter.py"]
