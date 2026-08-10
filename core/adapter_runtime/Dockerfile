FROM python:3.12-slim-bookworm AS adapter-base

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      baresip-core \
      ffmpeg \
      pulseaudio \
      pulseaudio-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY core/__init__.py core/interfaces.py /app/core/
COPY core/adapter_runtime /app/core/adapter_runtime
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin intercom \
 && mkdir -p /captures /run/intercom /app/intercom_integrations \
 && chown -R intercom:intercom /captures /run/intercom /app
USER intercom:intercom
ENV PYTHONPATH=/app
ENV XDG_RUNTIME_DIR=/run/intercom
EXPOSE 8080

FROM adapter-base AS synthetic
COPY intercom_integrations/__init__.py intercom_integrations/synthetic.py /app/intercom_integrations/
COPY integrations/synthetic/adapter.py /app/integrations/synthetic/adapter.py
CMD ["python3", "/app/integrations/synthetic/adapter.py"]

FROM adapter-base AS rtsp_camera
USER root:root
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      baresip-gstreamer \
      gstreamer1.0-libav \
      gstreamer1.0-plugins-good \
 && rm -rf /var/lib/apt/lists/* \
 && chown -R intercom:intercom /app
USER intercom:intercom
COPY intercom_integrations/__init__.py intercom_integrations/rtsp_camera.py /app/intercom_integrations/
COPY integrations/rtsp-camera/adapter.py /app/integrations/rtsp-camera/adapter.py
CMD ["python3", "/app/integrations/rtsp-camera/adapter.py"]

FROM adapter-base AS voice_pe
COPY intercom_integrations/__init__.py intercom_integrations/voice_pe.py /app/intercom_integrations/
COPY integrations/voice-pe/adapter.py /app/integrations/voice-pe/adapter.py
CMD ["python3", "/app/integrations/voice-pe/adapter.py"]
