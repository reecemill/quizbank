#!/bin/sh
# Starts the app inside the Docker image.
set -e

# On Hugging Face Spaces, SPACE_HOST is the public hostname (like
# user-quizbank.hf.space), served over HTTPS by a proxy in front of the app.
if [ -n "$SPACE_HOST" ]; then
  export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-$SPACE_HOST}"
  export DJANGO_CSRF_TRUSTED_ORIGINS="${DJANGO_CSRF_TRUSTED_ORIGINS:-https://$SPACE_HOST}"
  export DJANGO_BEHIND_HTTPS_PROXY=1
fi

# Without a configured key, make a new random one each start. Sign-ins end on a
# restart, which is fine: the demo database resets then too.
if [ -z "$DJANGO_SECRET_KEY" ]; then
  DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')"
  export DJANGO_SECRET_KEY
fi

# One process with threads, so the embedding model loads once and SQLite has a
# single writer process.
exec gunicorn quizbank.wsgi --bind 0.0.0.0:7860 --workers 1 --threads 4 --timeout 120
