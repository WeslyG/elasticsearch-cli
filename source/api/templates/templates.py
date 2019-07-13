
import click
import json
from source.es_connect import es_connect


def get_templates(name, local, timeout, format):
    es = es_connect()
    indices = es.cat.templates(
        name=name, local=local, master_timeout=timeout, format=format)
    if format == 'json':
        click.echo(json.dumps(indices, indent=4))
    else:
        click.echo(indices)

def delete_templates(name, timeout):
    es = es_connect()
    click.echo(es.indices.delete_template(name=name, master_timeout=timeout))

