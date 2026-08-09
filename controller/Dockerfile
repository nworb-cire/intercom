FROM python:3.13.5-alpine@sha256:37b14db89f587f9eaa890e4a442a3fe55db452b69cca1403cc730bd0fbdc8aaf

WORKDIR /app
COPY controller.py ./
USER 65534:65534
EXPOSE 8099
CMD ["python", "/app/controller.py"]
