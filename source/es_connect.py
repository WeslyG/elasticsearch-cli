from elasticsearch import Elasticsearch
import os

host = os.environ.get('ES_HOST')
port = os.environ.get('ES_PORT')

name = os.environ.get('ES_USERNAME')
secret = os.environ.get('ES_PASSWORD')

ssl = os.environ.get('ES_SSL')
ssl_verify = os.environ.get('ES_SSL_VERIFY')
ssl_ca = os.environ.get('ES_SSL_CA')
ssl_cert = os.environ.get('ES_SSL_CERT')
ssl_key = os.environ.get('ES_SSL_KEY')

def es_connect():
    return Elasticsearch(
            host=host,
            maxsize=25,
            port=port,
            http_auth=(name, secret),
            use_ssl=ssl,
            verify_certs=ssl_verify,
            ca_certs=ssl_ca,
            client_cert=ssl_cert,
            client_key=ssl_key)
