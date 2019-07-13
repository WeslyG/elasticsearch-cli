#!/usr/bin/python
# coding=utf-8

import click
import json
from source.api.cluster import cluster_api
from source.api.nodes import nodes_api
from source.api.master import master_api
from source.api.info import get_info

# indices
from source.api.indices import get_indices
from source.api.indices import open_indices
from source.api.indices import close_indices
from source.api.indices import delete_indices
from source.api.indices import create_indices

# shards
from source.api.shards import get_shards

# settings
from source.api.settings import get_settings

# templates
from source.api.templates import get_templates
from source.api.templates import delete_templates

# allocation
from source.api.allocation import allocation_explain
from source.api.allocation import allocation_enable

# validators
from source.libs.timeout_validator import timeout_validator
from source.libs.format_validator import format_validator
from source.libs.status_validator import status_validator
from source.libs.name_validator import name_validator


@click.group()
def cli():
    pass

@cli.group()
def indices():
    '''
    indices/
    '''
    pass


@cli.group()
def shards():
    '''
    shards/
    '''
    pass


@cli.group()
def templates():
    '''
    templates/
    '''
    pass


@cli.group()
def settings():
    '''
    cluster/_settings
    '''
    pass


@cli.group()
def allocation():
    '''
    allocation/
    '''
    pass

# allocation
@allocation.command()
def explain():
    '''
    allocation/explain
    '''
    allocation_explain()


# allocation
@allocation.command()
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.argument('name', nargs=-1)
def set(name, timeout):
    '''
    allocation/explain
    '''
    valid_name = name_validator(name[0])
    valid_time = timeout_validator(timeout)
    allocation_enable(valid_name, valid_time)


# settings
@settings.command()
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.option('-f', '--flat', is_flag=True, help='Return settings in flat format')
def get(timeout, flat):
    '''
    _cluster/settings
    '''
    valid_time = timeout_validator(timeout)
    get_settings(valid_time, flat)


# templates
@templates.command()
@click.option('-l', '--local', is_flag=True, help='BOOL Does not send a request to the master')
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.option('-f', '--format', default='text', help='Output format. Can be json or text')
@click.argument('name', nargs=-1)
def get(name, local, timeout, format):
    '''
    _cat/shards
    '''
    valid_format = format_validator(format)
    valid_time = timeout_validator(timeout)
    get_templates(name, local, valid_time, valid_format)


@templates.command()
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.argument('name', nargs=-1)
def delete(name, timeout):
    '''
    _template/delete
    '''
    valid_time = timeout_validator(timeout)
    delete_templates(name, valid_time)

# shards
@shards.command()
@click.option('-l', '--local', is_flag=True, help='BOOL Does not send a request to the master')
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.option('-f', '--format', default='text', help='Output format. Can be json or text')
@click.argument('name', nargs=-1)
def get(name, local, timeout, format):
    '''
    _cat/shards
    '''
    valid_format = format_validator(format)
    valid_time = timeout_validator(timeout)
    get_shards(name, local, valid_time, valid_format)


# indices
# TODO: парсит директорию на предмет наличия regexp потому имя индекса можно передать только в ковычках, что не круто
@indices.command()
@click.option('-l', '--local', is_flag=True, help='BOOL Does not send a request to the master')
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.option('-s', '--status', default=None, help='get indices in status "Green", "Yellow", "Red"')
@click.option('-f', '--format', default='text', help='Output format. Can be json or text')
@click.argument('name', nargs=-1)
def get(name, local, timeout, status, format):
    '''
    _cat/indices
    '''
    valid_format = format_validator(format)
    valid_time = timeout_validator(timeout)
    valid_status = status_validator(status)
    get_indices(name, local, valid_time, valid_status, valid_format)


# indices open
@indices.command()
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.argument('name', nargs=-1)
def open(name, timeout):
    '''
    indices/_open
    '''
    valid_time = timeout_validator(timeout)
    open_indices(name, valid_time)


# indices close
@indices.command()
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.argument('name', nargs=-1)
def close(name, timeout):
    '''
    indices/_open
    '''
    valid_time = timeout_validator(timeout)
    close_indices(name, valid_time)


# indices close
@indices.command()
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.argument('name', nargs=-1)
def delete(name, timeout):
    '''
    indices/delete
    '''
    valid_time = timeout_validator(timeout)
    delete_indices(name, valid_time)

# indices close


@indices.command()
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.argument('name', nargs=-1)
def create(name, timeout):
    '''
    indices/create
    '''
    valid_time = timeout_validator(timeout)
    create_indices(name, valid_time)


# cluster
@cli.command()
@click.option('-l', '--local', is_flag=True, help='BOOL Does not send a request to the master')
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.option('-i', '--index', default='', help='get health for index')
def health(local, timeout, index):
    '''
    _cluster/health
    '''
    valid_time = timeout_validator(timeout)
    cluster_api(local, valid_time, index)


# root
@cli.command()
@click.option('-l', '--local', is_flag=True, help='Does not send a request to the master')
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.option('-f', '--format', default='text', help='Output format. Can be json or text')
def nodes(local, timeout, format):
    '''
    _cat/nodes
    '''
    valid_time = timeout_validator(timeout)
    valid_format = format_validator(format)
    nodes_api(local, valid_time, valid_format)


@cli.command()
def info():
    '''
    /
    '''
    get_info()


@cli.command()
@click.option('-l', '--local', is_flag=True, help='Does not send a request to the master')
@click.option('-t', '--timeout', default='30s', help='master_timeout params, can be int (30) or string (30s) ')
@click.option('-f', '--format', default='text', help='Output format. Can be json or text')
def master(local, timeout, format):
    '''
    _cat/master
    '''
    valid_time = timeout_validator(timeout)
    valid_format = format_validator(format)
    master_api(local, valid_time, format)


if __name__ == '__main__':
    cli()
