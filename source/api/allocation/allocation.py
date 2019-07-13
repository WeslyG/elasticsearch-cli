
import click
import json
from source.es_connect import es_connect


def allocation_explain():
    es = es_connect()
    allocation = es.cluster.allocation_explain()
    click.echo(json.dumps(allocation, indent=4))


def allocation_enable(status, timeout):
    es = es_connect()
    settings = {"persistent": { "cluster.routing.allocation.enable": status}}
    enable = es.cluster.put_settings(body=settings, timeout=timeout)
    click.echo(json.dumps(enable, indent=4))

