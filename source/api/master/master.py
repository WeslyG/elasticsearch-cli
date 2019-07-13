import click
import json
from source.es_connect import es_connect


def master_api(local, timeout, format):
    es = es_connect()
    master = (es.cat.master(v=True, local=local,
                            master_timeout=timeout, format=format))
    if format == 'json':
        click.echo(json.dumps(master, indent=4))
    else:
        click.echo(master)
