from elasticsearch import Elasticsearch


def es_connect():
    return Elasticsearch("localhost", maxsize=25, port=9200)
