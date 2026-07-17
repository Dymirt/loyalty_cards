FROM debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        apache2 \
        build-essential \
        ca-certificates \
        default-libmysqlclient-dev \
        libapache2-mod-wsgi-py3 \
        libffi-dev \
        libjpeg62-turbo-dev \
        libssl-dev \
        mariadb-client \
        openssl \
        pkg-config \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
        swig \
        zip \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /var/www/loyalty_platform

COPY requirements-remote.txt /tmp/requirements-remote.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements-remote.txt

# The legacy host exposes Django admin assets through this absolute symlink.
# Recreate its target in the container using the pinned virtualenv installation.
RUN mkdir -p /usr/lib/python3/dist-packages/django/contrib/admin/static \
    && ln -s /opt/venv/lib/python3.11/site-packages/django/contrib/admin/static/admin \
        /usr/lib/python3/dist-packages/django/contrib/admin/static/admin

COPY docker/apache/loyalty.conf /etc/apache2/sites-available/loyalty.conf
COPY docker/entrypoint.sh /usr/local/bin/loyalty-entrypoint

RUN a2dissite 000-default \
    && a2ensite loyalty \
    && a2enmod headers \
    && chmod 0755 /usr/local/bin/loyalty-entrypoint

EXPOSE 80

ENTRYPOINT ["/usr/local/bin/loyalty-entrypoint"]
CMD ["apache2ctl", "-D", "FOREGROUND"]
