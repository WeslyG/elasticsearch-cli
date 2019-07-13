import click
import json
from source.es_connect import es_connect


def get_indices(index, local, timeout, status, format):
    es = es_connect()
    indices = es.cat.indices(index=index, local=local, master_timeout=timeout, health=status, format=format)
    if format == 'json':
        click.echo(json.dumps(indices, indent=4))
    else:
        click.echo(indices)

def close_indices(name, timeout):
    es = es_connect()
    click.echo(es.indices.close(index=name, master_timeout=timeout))


def open_indices(name, timeout):
    es = es_connect()
    click.echo(es.indices.open(index=name, master_timeout=timeout))


def delete_indices(name, timeout):
    es = es_connect()
    click.echo(es.indices.delete(index=name, master_timeout=timeout))


def create_indices(name, timeout):
    es = es_connect()
    # TODO: body (settings and mapping)
    click.echo(es.indices.create(index=name, master_timeout=timeout))
