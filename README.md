### Elasticsearch - CLI

### Support

- Elasticsearch 6

![alt text](https://github.com/WeslyG/elasticsearch-cli/blob/master/etc/screen.png?raw=true)


### Why?

I'm tired of typing in the console ```curl localhost:9200```, I'm a man, not a machine. And I don't want a GUI, my cluster won't stand it!

This is not an official cli for Elasticsearch. I did it for myself and you are free to use it.

Under the hood it's just python Сlick framework and Elasticsearch python client.

I wanted to make the cli as clear and simple as possible, so I removed the standard abstraction _cat/ it is not clear, and therefore causes a lot of pain when to do something quickly.

This is the first version of the cli, however you can already get most of the entities of the elastic through it. She even has tests!

The roadmap and existing features are presented below, the rest we can find in autocomplete of your shell.


### DEMO time!

Just imagine what it is

```
es allocation set disable
```

Here you replace it

```
curl -XPOST localhost:9200/cluster/_settings -H 'Content-Type: application/json' -d '{"persistent": { "cluster.routing.allocation.enable": "none"}}'
```

Or this

```
es indices get 'name*'
```

This

```
curl localhost:9200/_cat/indices/name*
```

Of course, you can use dev_tools inside kibana but it's a cli!


## ROADMAP

#### Config
- [ ] Multi instance configuration
- [ ] Switch between instance

#### Es api
- [x] info (/)
- [x] health
- [x] allocation
    - [x] explain
    - [x] set
        - [x] all
        - [x] primaries
        - [x] new_primaries
        - [x] none
        - [x] disable (none)
        - [x] enable (all)
        - [x] default (null)
- [ ] Settings
    - [x] Get
    - [ ] Set config
- [ ] Reroute
    - [ ] auto reroute
    - [ ] reroute?retry_failed
- [x] Indices
   - [x] get
   - [x] delete
   - [x] open
   - [x] close
   - [x] create
- [ ] Shards
    - [x] get
        - [ ] relocatable
        - [ ] unasigned
- [ ] Templates
    - [x] get
    - [x] delete
    - [ ] create
- [x] Nodes
  - [x] Get
- [x] Master
  - [x] Get
- [ ] Mapping
- [ ] Threads
- [ ] Tasks
- [ ] Snapshots

#### Local develop

$ virtualenv venv
$ . venv/bin/activate
$ pip install --editable .

#### OR Bash

```
chmod + x run.sh
./run.sh

```

#### Tests

pytest
