#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import json
import os

SECRETS_FILE = 'secrets.json'

def get_cached_value_or_set(name: str, generator: callable):

    existing_value = get_cached_value(name)

    if existing_value is not None:
        return existing_value

    value = generator()
    set_cached_value(name, value)
    return value


def get_cached_value(name: str):
    secrets_file = _get_secrets_file()

    if os.path.exists(secrets_file):
        with open(secrets_file, 'r') as file:
            try:
                data = json.load(file)
                value = data.get(name)
                if value:
                    return value
            except json.JSONDecodeError:
                return None
    return None


def set_cached_value(name: str, value: str):
    secrets_file = _get_secrets_file()

    if os.path.exists(secrets_file):
        with open(secrets_file, 'r') as file:
            try:
                data = json.load(file)
            except json.JSONDecodeError:
                raise Exception("Could not read secrets file. Aborting.")
    else:
        data = {}
    data[name] = value
    # Atomic write: write to a sibling temp file then os.replace into place.
    # A crash mid-write leaves the previous valid secrets.json intact, which
    # matters because losing this file forces a full interactive re-login that
    # cannot run inside a container (see DEPLOYMENT.md).
    tmp_path = secrets_file + '.tmp'
    with open(tmp_path, 'w') as file:
        json.dump(data, file)
        file.flush()
        os.fsync(file.fileno())
    os.replace(tmp_path, secrets_file)


def _get_secrets_file():
    custom = os.environ.get('SECRETS_PATH')
    if custom:
        return custom
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, SECRETS_FILE)