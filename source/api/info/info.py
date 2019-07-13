import click
from source.es_connect import es_connect


def get_info():
    es = es_connect()
    info = es.info()
    click.echo('{')
    click.echo(' name: %s,' % info['name'])
    click.echo(' cluster_name: %s,' % info['cluster_name'])
    click.echo(' cluster_uuid: %s,' % info['cluster_uuid'])
    click.echo(' version: {')
    click.echo('  number: %s,' % info['version']['number'])
    click.echo('  build_flavor: %s,' % info['version']['build_flavor'])
    click.echo('  build_type: %s,' % info['version']['build_type'])
    click.echo('  build_hash: %s,' % info['version']['build_hash'])
    click.echo('  build_date: %s,' % info['version']['build_date'])
    click.echo('  build_snapshot: %s,' % info['version']['build_snapshot'])
    click.echo('  lucene_version: %s,' % info['version']['lucene_version'])
    click.echo('  minimum_wire_compatibility_version: %s,' %
               info['version']['minimum_wire_compatibility_version'])
    click.echo('  minimum_index_compatibility_version: %s,' %
               info['version']['minimum_index_compatibility_version'])
    click.echo('  },')
    click.echo(' tagline: %s,' % info['tagline'])
    click.echo('}')
