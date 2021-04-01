FROM ubuntu:latest
ENV ELASTIC_CLI_HOME /opt/elasticsearch-cli
ARG URL=https://github.com/WeslyG/elasticsearch-cli.git

WORKDIR /opt
RUN apt-get update && apt-get upgrade -y
RUN apt-get -y install apt-utils build-essential python3 python3-dev python3-pip libssl-dev git wget unzip

RUN git clone "${URL}"
WORKDIR "${ELASTIC_CLI_HOME}"

ADD requirements.txt ./

RUN pip3 install -r requirements.txt
RUN pip3 install --upgrade pip

RUN pip3 install wheel && \
    pip3 install "setuptools>=11.3"

RUN python3 setup.py install
