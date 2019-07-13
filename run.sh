#!/bin/bash

virtualenv venv
. venv/bin/activate
pip install --editable .
