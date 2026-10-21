FROM tomsquest/docker-radicale
#:latest AS base

# add system package
RUN apk add --no-cache nano

# install radicale/python plugins
#RUN /venv/bin/pip install git+https://github.com/Unrud/RadicaleInfCloud
RUN /venv/bin/pip install --upgrade git+https://github.com/Rilele/RadicaleInfCloud.git
