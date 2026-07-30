FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.116.1 \
    uvicorn[standard]==0.35.0 \
    markdown==3.8.2 \
    latex2mathml==3.81.0 \
    bleach==6.2.0

COPY --link ./ /app

ENV RESEARCH_ROOT=/research
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
