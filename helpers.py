import os
import re
import json

from flask import redirect, session
from functools import wraps

CONFIG_FN = "config.json"


def config_file_exists():
    if os.path.exists(CONFIG_FN):
        return True

    return False


def make_config_file(host_name, ssh_username, ip_address, mac_address):
    ''' Defines the initial structure of the JSON configuration file '''
    base_config = {
        # We have a list of hosts
        "hosts":
        [
            # Within which is one or multiple dictionaries containing their attributes
            {
                "name": host_name,
                "ssh_username": ssh_username,
                "ip_address": ip_address,
                "mac_address": mac_address,
                # One of those attributes is a list of clients, which contains * dictionaries
                "clients":
                [

                ]
            }
        ]
    }

    update_config(base_config)


def load_config():
    ''' Loads the configuration using the constant declared at the top of this file '''
    with open(CONFIG_FN, "r") as config_file:
        return json.load(config_file)


def update_config(new_config):
    '''
    Overwrites any previously-existing config file with the new
    configuration data
    '''

    with open(CONFIG_FN, "w") as config_file:
        json.dump(new_config, config_file)


def add_host_to_config(host_name, ssh_username, ip_address, mac_address):
    ''' Returns True on success, False on failure '''
    config = load_config()

    for host in config["hosts"]:
        if host["name"] == host_name:
            # If the host is already in our list, we don't add it and return early
            return False

    # Otherwise we add all of the information into our config
    config["hosts"].append({
        "name": host_name,
        "ssh_username": ssh_username,
        "ip_address": ip_address,
        "mac_address": mac_address,
        "clients":
        [

        ]
    })
    # And update it
    update_config(config)
    return True


def add_client_to_host(host_name, client_name, client_resolution, ssh_command):
    ''' Returns True on success, False on failure '''
    config = load_config()
    for idx, host in enumerate(config["hosts"]):
        # Look in the hosts until we find the correct one
        if host["name"] != host_name:
            continue
        # We return early if the user tries to add a client that's already present
        client_already_present = client_name in [x["name"] for x in config["hosts"][idx]["clients"]]
        if client_already_present:
            return False

        # Otherwise we keep going and add the client info to the selected host
        config["hosts"][idx]["clients"].append({
            "name": client_name,
            "resolution": client_resolution,
            "ssh_command": ssh_command
        })
        update_config(config)
        return True

    return False


def hosts_config_required(f):
    """
    Decorate routes to require At least one host configured.

    https://flask.palletsprojects.com/en/1.1.x/patterns/viewdecorators/
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not config_file_exists():
            return redirect("/hosts-config")
        return f(*args, **kwargs)
    return decorated_function