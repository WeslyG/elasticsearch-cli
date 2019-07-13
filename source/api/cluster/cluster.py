import click
import json
import collections
from source.es_connect import es_connect
from source.libs.get_color import get_color

def cluster_api(local, timeout, index):
    es = es_connect()
    cluster = es.cluster.health(local=local,
                                master_timeout=timeout, index=index)
    click.echo('{')
    click.echo(' cluster_name: %s,' % cluster['cluster_name'])
    click.echo(' status: %s,' % click.style(
        str(cluster['status']), fg=cluster['status']))
    click.echo(' timed_out: %s ,' % cluster['timed_out'])
    click.echo(' number_of_nodes: %s,' % cluster['number_of_nodes'])
    click.echo(' number_of_data_nodes: %s,' % cluster['number_of_data_nodes'])
    click.echo(' active_primary_shards: %s,' %
               str(cluster['active_primary_shards']))
    click.echo(' active_shards: %s,' % str(cluster['active_shards']))
    click.echo(' relocating_shards:  ' +
               click.style(str(cluster['relocating_shards']), fg=get_color(cluster['relocating_shards'])))
    click.echo(' initializing_shards: ' +
               click.style(str(cluster['initializing_shards']), fg=get_color(cluster['initializing_shards'])))
    click.echo(' unassigned_shards: ' +
               click.style(str(cluster['unassigned_shards']), fg=get_color(cluster['unassigned_shards'])))
    click.echo(' delayed_unassigned_shards: %s,' %
               str(cluster['delayed_unassigned_shards']))

    click.echo(' number_of_pending_tasks: %s,' %
               str(cluster['number_of_pending_tasks']))
    click.echo(' number_of_in_flight_fetch: %s,' %
               str(cluster['number_of_in_flight_fetch']))
    click.echo(' task_max_waiting_in_queue_millis: %s,' %
               str(cluster['task_max_waiting_in_queue_millis']))
    click.echo(' active_shards_percent_as_number: %s' %
               str(cluster['active_shards_percent_as_number']))
    click.echo('}')
