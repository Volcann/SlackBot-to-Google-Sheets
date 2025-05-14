# 1. Base image
FROM python:3.11-slim

# 2. Prevent .pyc files & enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 3. Set working dir
WORKDIR /app

# 4. System deps
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# 5. Copy & install Python deps
COPY requirements.txt /app/
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# 6. Copy project files
COPY . /app/

# 7. Collect static files (optional – only if you serve them via Django)
# RUN python manage.py collectstatic --noinput

# 8. Expose port for your Django app
EXPOSE 8000

# 9. Run migrations + start Django’s dev server
#    If you have a custom Slack‐bot management command, swap "runserver" for it:
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8000"]
