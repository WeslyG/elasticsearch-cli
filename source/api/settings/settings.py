
import click
import json
from source.es_connect import es_connect


def get_settings(timeout, flat):
    es = es_connect()
    settings = es.cluster.get_settings( master_timeout=timeout, flat_settings=flat)
    click.echo(json.dumps(settings, indent=4))


def set_config():
    es = es_connect()
    pass
