import click
import json
from source.es_connect import es_connect


def get_shards(name, local, timeout, format):
    es = es_connect()
    shards = es.cat.shards(
        index=name, local=local, master_timeout=timeout, format=format)
    if format == 'json':
        click.echo(json.dumps(shards, indent=4))
    else:
        click.echo(shards)
