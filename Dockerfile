# The public demo: the app with sample courses, a simulated class, and the
# trained essay grader built into the image. Every container starts from that
# same fresh database, so the demo resets whenever it restarts.
# Made for Hugging Face Spaces (see deploy/), but runs anywhere:
#   docker build -t quizbank . && docker run -p 7860:7860 quizbank

FROM python:3.12-slim

# The UNT dataset's server leaves out its intermediate certificate, which curl
# on Linux can't fetch by itself (browsers and macOS do). Add that certificate
# to the system store, only after checking that a trusted root signed it, so
# the download stays verified.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl openssl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL http://crt.sectigo.com/InCommonRSAOVSSLCA3.crt -o /tmp/incommon.der \
    && openssl x509 -inform DER -in /tmp/incommon.der -out /usr/local/share/ca-certificates/incommon-rsa-ov-ssl-ca-3.crt \
    && openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt /usr/local/share/ca-certificates/incommon-rsa-ov-ssl-ca-3.crt \
    && update-ca-certificates \
    && rm /tmp/incommon.der

# Hugging Face Spaces run containers as user 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
RUN mkdir -p $HOME/app
WORKDIR $HOME/app

# CPU-only PyTorch, a fraction of the size of the default build.
RUN pip install --user torch --index-url https://download.pytorch.org/whl/cpu
COPY --chown=user requirements.txt .
RUN pip install --user -r requirements.txt
COPY --chown=user . .

# The shared demo account, shown on the sign-in page.
ENV QUIZBANK_DEMO_USERNAME=demo \
    QUIZBANK_DEMO_PASSWORD=quizbank-demo

# Downloads the datasets and embedding model, trains the grader, and builds the
# demo database. The secret key here is only for these build steps.
RUN export DJANGO_SECRET_KEY=build-only \
    && python manage.py collectstatic --noinput \
    && python manage.py migrate \
    && python manage.py train_essay_grader \
    && python manage.py setup_demo

EXPOSE 7860
CMD ["sh", "deploy/start.sh"]
