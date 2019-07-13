### Elasticsearch - CLI

### Support

- Elasticsearch 6

![alt text](https://lh3.googleusercontent.com/PL3zkKtbylbyROC9MDXP1i98-IdzAY_q6KTJDNJsbrAp5hiDX48zKDWdr1U9gAI3TnVPMq8tNtlNCWXia4oBKrqjS0q5sVlNHSi13f2rJG-XqlZsZc_hsjHnzJdv8i2GmX1pUjtXz1Whg59hz1-DGFPCR7chGWHvWn9cC6oOf2Si8Z3LlNbQM5FA6mRq_AEY_I7HPshrHbgmvIdNgoXT-Sw_5E3H5r5Ywm1W6VZ6gJFIOtr3mjBpH-TE0-ENADGqo34wla_w3z5bLQqnCAWFeGYjdF2WJgAC6FNOurPfipU-bOenQ9saE6lPcuOcBaTmR_IyD4hUAaG7NV7wS2XQVuIxnzw-nzFOqlzeD91N0S7shWZxvMK1WFBkpmDM2aArCxSAZ_AiCqkNsw6OO7vgwulXlxfETnzuQpCW4L_xOS2eJAN-R1bbNoHV5OCu6Aq6ne8lJgGCFmEqM1DIiUUSVoDV2O0bPEMmydp3Igl_LhaqZsRCVHIDK_vcuy3oQrLg3pAlwHOZn-EMhfmhtac9KZ0PyCPvojF_6LgYycKZ7Ks6jusjj3HzH8FlNFL9Z4NgfwXA3FOUdUEUSetXD2GsaPkYhCtcd3HOOmiav8R6GmpAUQ_XVdtdjHvXU2oWb_tXrvzMnBTfnpN51jUlqmJf2F6_AeNLzlE=w496-h318-no)


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
