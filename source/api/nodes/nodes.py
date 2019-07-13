import click
import json
from source.es_connect import es_connect


def nodes_api(local, timeout, format):
    es = es_connect()
    nodes = es.cat.nodes(v=True, local=local, master_timeout=timeout,
                         format=format)
    if format == 'json':
        click.echo(json.dumps(nodes, indent=4))
    else:
        click.echo(nodes)
