from flask import Flask, flash, redirect, render_template, request
from flask_session import Session

from helpers import (hosts_config_required, make_config_file, load_config,
                     config_file_exists, add_host_to_config, add_client_to_host,
                     CONFIG_FN)

# We use the ping3 library to be able to communicate the status of hosts to the user
from ping3 import ping
# We use wakeonlan so that local machines to the server can be turned on remotely
from wakeonlan import send_magic_packet

# We use the paramiko library to send SSH commands
from paramiko import SSHClient, AutoAddPolicy, SSHException

# Configure application
app = Flask(__name__)

# Configure session to use filesystem (instead of signed cookies)
# app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/", methods=["GET", "POST"])
@hosts_config_required
def index():
    config = load_config()

    # We ping all hosts and ultimately add the result into the config that's passed to our template
    for idx, host in enumerate(config["hosts"]):
        try:
            # If the ping is successful (no timeout)
            if ping(host["ip_address"]):
                config["hosts"][idx]["ping"] = "success"
            else:
                config["hosts"][idx]["ping"] = "failure"
        # The ping3 library can raise an error on some systems if it doesn't have elevated privileges
        except PermissionError:
            config["hosts"][idx]["ping"] = "warning"

    return render_template("index.html", config=config)


@app.route("/hosts-config", methods=["GET", "POST"])
def host_config():
    if request.method == "GET":
        return render_template("hosts-config.html")

    host_name, ssh_username, ip_address, mac_address = (request.form.get("host_name"),
                                                        request.form.get("ssh_username"),
                                                        request.form.get("ip_address"),
                                                        request.form.get("mac_address"))

    # Validate that all fields are filled
    if not host_name or not ssh_username or not ip_address or not mac_address:
        flash("Must fill all fields", "danger")
        return render_template("/hosts-config.html")

    if config_file_exists():
        config_successfully_updated = add_host_to_config(host_name, ssh_username, ip_address, mac_address)
        if not config_successfully_updated:
            flash("A host with this name already exists, consider editing it instead", "danger")
            # We redirect to the homepage so that the host can be edited (TODO)
            return redirect("/")
    else:
        # If the user has no config file setup, we create it with the provided info
        make_config_file(host_name, ssh_username, ip_address, mac_address)

    flash("Host added successfully!", "success")

    # On setup of any host, we give the user a bit more information about the host's reachability
    try:
        if ping(ip_address):
            flash("Host is reachable by the server", "success")
        else:
            flash("Could not reach entered IP, may be incorrect", "warning")
    except PermissionError:
        flash("The server can't ping the host, run with elevated privileges for more functionality", "warning")

    return redirect("/")


@app.route("/clients-config", methods=["GET", "POST"])
@hosts_config_required
def client_config():
    if request.method == "GET":
        # We load all host names so that the user can select which host to add the new client to
        hosts = [x["name"] for x in load_config()["hosts"]]
        return render_template("clients-config.html", hosts=hosts)

    host_name, name, resolution, ssh_command = (request.form.get("host_name"),
                                                request.form.get("client_name"),
                                                request.form.get("resolution"),
                                                request.form.get("ssh_command"))

    # We validate that all fields are filled
    if not host_name or not name or not ssh_command:
        flash("All required fields must be filled", "danger")
        return redirect("/clients-config")
    if not resolution:
        resolution = None

    if add_client_to_host(host_name, name, resolution, ssh_command):
        flash("Client added successfully", "success")
    else:
        flash("Invalid client entered! Make sure you're not trying to add a client that already exists.", "danger")
        redirect("/clients-config")

    return redirect("/")


@app.route("/wakeup", methods=["GET"])
@hosts_config_required
def wakeup():
    ''' A sort of API to send magic packets to a host located in the config file '''
    host_label = request.args.get("host-label")

    # We validate that the parameter is given
    if not host_label:
        flash("Expected a host label but did not receive any", "danger")
        return redirect("/")

    # We make sure the host is in our config
    hosts = load_config()["hosts"]
    if host_label not in [x["name"] for x in hosts]:
        flash("This host doesn't exist!", "danger")
        return redirect("/")

    for host in hosts:
        if host["name"] != host_label:
            continue
        try:
            send_magic_packet(host["mac_address"])
            flash("Sent magic packet!", "success")
        except ValueError:
            flash("Invalid MAC address! Are you sure the host is configured correctly?", "danger")
        finally:
            return redirect("/")

    return redirect("/")


@app.route("/command", methods=["GET"])
@hosts_config_required
def run_client_command():
    ''' A sort of API to run SSH commands on a host located in the config file '''
    host_label = request.args.get("host-label")
    client_label = request.args.get("client")

    # We validate that both parameters are given
    if not host_label:
        flash("Expected a host label but did not receive any", "danger")
        return redirect("/")
    if not client_label:
        flash("Expected a client label but did not receive any", "danger")
        return redirect("/")

    hosts = load_config()["hosts"]
    # We make sure the host is in our config
    if host_label not in [x["name"] for x in hosts]:
        flash("This host doesn't exist!", "danger")
        return redirect("/")

    for host in hosts:
        # We don't do anything if the host doesn't match the one given in the GET request
        if host["name"] != host_label:
            continue

        clients = [x for x in host["clients"]]
        # We make sure the client is in our config
        if client_label not in [x["name"] for x in clients]:
            flash("This client doesn't exist!", "danger")
            return redirect("/")
        for client in clients:
            # We don't do anything if the client doesn't match the one given in the GET request
            if client["name"] != client_label:
                continue
            # We grab the command associated with the client
            ssh_command = client["ssh_command"]

        user = host["ssh_username"]
        ip_address = host["ip_address"]

        # We setup a paramiko SSH tunnel
        # We assume the user has already copied over his SSH keys from the machine
        # That runs this flask app to the targeted host
        client = SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(AutoAddPolicy())
        try:
            # Connect and run the command
            client.connect(ip_address, username=user)
            stdin, stdout, stderr = client.exec_command(ssh_command)
            errors = [x for x in stderr]
            if not errors:
                flash("Command ran successfully", "success")
            else:
                # In case of any errors, we display them directly in the web interface
                flash("Command execution may have failed", "danger")
                flash(f"Command sent: {ssh_command}", "warning")
                for error in errors:
                    flash(error, "warning")

        except SSHException as e:
            flash(f"Error: {str(e)}", "danger")
            flash("Make sure you've copied over SSH keys.", "danger")

    return redirect("/")


@app.route("/about")
def about():
    return render_template("/about.html")


@app.route("/README")
def readme():
    with open("./README.md") as readme_file:
        readme = readme_file.read()

    # The readme template renders any markdown appropriately
    return render_template("/README.html", readme=readme)