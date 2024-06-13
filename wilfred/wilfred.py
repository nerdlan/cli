# -*- coding: utf-8 -*-

#################################################################
#                                                               #
# Wilfred                                                       #
# Copyright (C) 2020-2022, Vilhelm Prytz, <vilhelm@prytznet.se> #
#                                                               #
# Licensed under the terms of the MIT license, see LICENSE.     #
# https://github.com/wilfred-dev/wilfred                        #
#                                                               #
#################################################################

import click
import codecs
import locale
import os
import sys

from halo import Halo
from pathlib import Path
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect
from time import sleep
from tabulate import tabulate
from shutil import get_terminal_size

from wilfred.docker_conn import docker_client
from wilfred.version import version, commit_hash, commit_date
from wilfred.api.config_parser import Config, NoConfiguration
from wilfred.api.database import (
    session,
    database_path,
    Server,
    EnvironmentVariable,
    Port,
)
from wilfred.api.servers import Servers
from wilfred.api.images import Images, ImageAPIMismatch, ImagesOutdated
from wilfred.message_handler import warning, error, ui_exception
from wilfred.core import is_integer, random_string, check_for_new_releases
from wilfred.migrate import Migrate
from wilfred.api.server_config import ServerConfig
from wilfred.decorators import configuration_present


config = Config()

try:
    config.read()
except NoConfiguration:
    warning("Wilfred is not yet configured. Run `wilfred setup` to configure Wilfred.")
except Exception as e:
    ui_exception(e)


images = Images()

if not os.environ.get("WILFRED_SKIP_DOCKER", False):
    try:
        servers = Servers(docker_client(), config.configuration, images)
    except Exception as e:
        ui_exception(e)

if not images.check_if_present():
    with Halo(
        text="Downloading default images", color="yellow", spinner="dots"
    ) as spinner:
        images.download()
        spinner.succeed("Images downloaded")

try:
    images.read_images()
except ImageAPIMismatch:
    with Halo(
        text="Downloading default images", color="yellow", spinner="dots"
    ) as spinner:
        images.download()
        spinner.succeed("Images downloaded")
    try:
        images.read_images()
    except Exception as e:
        ui_exception(e)
except ImagesOutdated:
    with Halo(
        text="Images outdated, refreshing default images",
        color="yellow",
        spinner="dots",
    ) as spinner:
        images.download()
        spinner.succeed("Images refreshed")
    try:
        images.read_images()
    except Exception as e:
        ui_exception(e)
except Exception as e:
    ui_exception(e)

# check
Migrate()

ENABLE_EMOJIS = False if sys.platform.startswith("win") else True


def print_version(ctx, param, value):
    """
    print version and exit
    """

    if not value or ctx.resilient_parsing:
        return

    _commit_hash = commit_hash[0:7]
    _snap = (
        f" via snap (revision {os.environ['SNAP_REVISION']})"
        if "SNAP" in os.environ and "SNAP_REVISION" in os.environ
        else ""
    )
    _python_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )

    check_for_new_releases(enable_emojis=ENABLE_EMOJIS)
    if str(version) == "0.0.0.dev0":
        click.echo(
            "".join(
                (
                    f"{'✨ ' if ENABLE_EMOJIS else ''}wilfred version ",
                    f"{_commit_hash}/edge (development build) built {commit_date}{_snap} (python {_python_version})",
                )
            )
        )
    else:
        click.echo(
            "".join(
                (
                    f"{'✨ ' if ENABLE_EMOJIS else ''}wilfred version ",
                    f"v{version}/stable (commit {_commit_hash}) built {commit_date}{_snap} (python {_python_version})",
                )
            )
        )

    ctx.exit()


def print_path(ctx, param, value):
    """
    print config/data paths
    """

    if not value or ctx.resilient_parsing:
        return

    click.echo(f"Configuration file: {click.format_filename(config.config_path)}")
    click.echo(f"Image config file: {click.format_filename(images.image_dir)}")
    click.echo(f"Database file: {click.format_filename(database_path)}")

    if config.configuration:
        _path = f"{click.format_filename(config.configuration['data_path'])}"

        if sys.platform.startswith("win"):
            _path = _path.replace("/", "\\")

        click.echo(f"Server data: {_path}")

    ctx.exit()


def pretty_list(data, tablefmt):
    for server in data:
        server.update(
            (
                k,
                str(v)
                .replace("running", click.style("running", fg="green"))
                .replace("stopped", click.style("stopped", fg="red"))
                .replace("installing", click.style("installing", fg="yellow")),
            )
            for k, v in server.items()
        )

    headers = {
        "id": click.style("ID", bold=True),
        "name": click.style("Name", bold=True),
        "image_uid": click.style("Image UID", bold=True),
        "memory": click.style("RAM", bold=True),
        "port": click.style("Port", bold=True),
        "status": click.style("Status", bold=True),
        "custom_startup": click.style("Custom startup", bold=True),
    }

    return tabulate(
        data,
        headers=headers,
        tablefmt=tablefmt,
    )


def main():
    # snap packages raise some weird ASCII codec errors, so we just force C.UTF-8
    if (
        codecs.lookup(locale.getpreferredencoding()).name == "ascii"
        and os.name == "posix"
    ):
        os.environ["LC_ALL"] = "C.UTF-8"
        os.environ["LANG"] = "C.UTF-8"

    cli()


@click.group()
@click.option(
    "--version",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
    help="Print version and exit",
)
@click.option(
    "--path",
    is_flag=True,
    callback=print_path,
    expose_value=False,
    is_eager=True,
    help="Print paths for configurations and server data",
)
def cli():
    """
    Wilfred - A CLI for managing game servers using Docker.

    Website - https://wilfredproject.org

    Official documentation - https://docs.wilfredproject.org

    Source code - https://github.com/wilfred-dev/wilfred

    Discord server for support - https://wilfredproject.org/discord
    """

    pass


@cli.command()
def setup():
    """Setup wilfred, create configuration."""

    if config.configuration:
        warning("A configuration file for Wilfred already exists.")
        click.confirm("Are you sure you wan't to continue?", abort=True)

    data_path = click.prompt(
        "Path for storing server data",
        default=f"{str(Path.home())}/wilfred-data/servers",
    )

    config.write(data_path)


@cli.command("servers")
def servers_list():
    """List all existing servers."""

    # run sync to refresh server state
    servers.sync()

    data = servers.all()

    click.echo(
        pretty_list(
            data,
            tablefmt="plain" if get_terminal_size((80, 20))[0] < 96 else "fancy_grid",
        )
    )


@cli.command("images")
@click.option("--refresh", help="Download the default images from GitHub", is_flag=True)
@click.option(
    "--repo",
    help="Specify repo to fetch images from during image refresh",
    default="wilfred-dev/images",
    show_default=True,
)
@click.option(
    "--branch",
    help="Specify branch to fetch images from during image refresh",
    default="master",
    show_default=True,
)
def list_images(refresh, repo, branch):
    """List images available on file."""

    if refresh:
        with Halo(
            text=f"Refreshing images [{repo}/{branch}]", color="yellow", spinner="dots"
        ) as spinner:
            try:
                images.download(repo=repo, branch=branch)
                images.read_images()
            except Exception as e:
                spinner.fail()
                ui_exception(e)

            spinner.succeed(f"Images refreshed [{repo}/{branch}]")

    click.echo(
        tabulate(
            images.data_strip_non_ui(),
            headers={
                "uid": click.style("UID", bold=True),
                "name": click.style("Image Name", bold=True),
                "author": click.style("Author", bold=True),
                "default_image": click.style("Default Image", bold=True),
            },
            tablefmt="fancy_grid",
        )
    )

    updated_at = click.style(
        images.image_fetch_date.strftime("%Y-%m-%d %H:%M:%S"), bold=True
    )
    will_refresh_in = click.style(
        str(images.image_time_to_refresh).split(".")[0], bold=True
    )

    click.echo(
        f"Default images last updated at {updated_at}, will refresh in {will_refresh_in}"
    )


@cli.command()
@click.option(
    "--console",
    help="Attach to server console immediately after creation.",
    is_flag=True,
)
@click.option(
    "--detach",
    help="Immediately detach during install.",
    is_flag=True,
)
@click.pass_context
@configuration_present
def create(ctx, console, detach):
    """Create a new server."""

    name = click.prompt("Server Name").lower()

    if " " in name:
        error("space not allowed in name", exit_code=1)

    click.secho("Available Images", bold=True)
    click.echo(
        tabulate(
            images.data_strip_non_ui(),
            headers={
                "uid": click.style("UID", bold=True),
                "name": click.style("Image Name", bold=True),
                "author": click.style("Author", bold=True),
                "default_image": click.style("Default Image", bold=True),
            },
            tablefmt="fancy_grid",
        )
    )

    image_uid = click.prompt("Image UID", default="minecraft-vanilla")

    if " " in image_uid:
        error("space not allowed in image_uid", exit_code=1)

    if not images.get_image(image_uid):
        error("image does not exist", exit_code=1)

    port = click.prompt("Port", default=images.get_image(image_uid)["default_port"])
    memory = click.prompt("Memory", default=1024)

    # create
    server = Server(id=random_string())

    try:
        server.name = name
    except ValueError as e:
        error(str(e), exit_code=1)

    server.image_uid = image_uid
    server.memory = memory
    server.port = port
    server.custom_startup = None
    server.status = "installing"

    session.add(server)

    try:
        session.commit()
    except IntegrityError as e:
        error(f"unable to create server {click.style(str(e), bold=True)}", exit_code=1)

    click.secho("Environment Variables", bold=True)

    # environment variables available for the container
    for v in images.get_image(image_uid)["variables"]:
        if not v["hidden"]:
            value = click.prompt(
                v["prompt"], default=v["default"] if v["default"] is not True else None
            )

        if v["hidden"]:
            value = v["default"]

        variable = EnvironmentVariable(
            server_id=server.id, variable=v["variable"], value=value
        )
        session.add(variable)

    try:
        session.commit()
    except IntegrityError as e:
        error(
            f"unable to create variables {click.style(str(e), bold=True)}", exit_code=1
        )

    # custom startup command
    if click.confirm("Would you like to set a custom startup command (optional)?"):
        custom_startup = click.prompt(
            "Custom startup command", default=images.get_image(image_uid)["command"]
        )

        server.custom_startup = custom_startup
        try:
            session.commit()
        except IntegrityError as e:
            error(
                f"unable to set startup command {click.style(str(e), bold=True)}",
                exit_code=1,
            )

    with Halo(text="Creating server", color="yellow", spinner="dots") as spinner:
        try:
            servers.install(
                server, skip_wait=True if detach else False, spinner=spinner
            )
        except Exception as e:
            spinner.fail()
            ui_exception(e)
        spinner.succeed("Server created")

    if console:
        ctx.invoke(start, name=name)
        ctx.invoke(server_console, name=name)


@cli.command("sync")
@configuration_present
def sync_cmd():
    """
    Sync all servers on file with Docker (start/stop/kill).
    """

    with Halo(text="Docker sync", color="yellow", spinner="dots") as spinner:
        try:
            servers.sync()
        except Exception as e:
            spinner.fail()
            ui_exception(e)
        spinner.succeed("Servers synced")


@cli.command(short_help="Start server")
@click.argument("name")
@click.option(
    "--console", help="Attach to server console immediately after start.", is_flag=True
)
@click.pass_context
@configuration_present
def start(ctx, name, console):
    """
    Start server

    NAME is the name of the server
    """

    try:
        servers.sync()
    except Exception as e:
        ui_exception(e)

    with Halo(text="Starting server", color="yellow", spinner="dots") as spinner:
        server = session.query(Server).filter_by(name=name.lower()).first()

        if not server:
            spinner.fail("Server does not exit")
            sys.exit(1)

        if server.status == "installing":
            spinner.fail("Server is installing, start blocked.")
            sys.exit(1)

        image = images.get_image(server.image_uid)

        if not image:
            error("Image UID does not exit", exit_code=1)

        try:
            ServerConfig(
                config.configuration, servers, server, image
            ).write_environment_variables()
        except Exception as e:
            ui_exception(e)

        try:
            servers.set_status(server, "running")
            servers.sync()
        except Exception as e:
            spinner.fail()
            ui_exception(e)

        spinner.succeed("Server started")

        if console:
            ctx.invoke(server_console, name=name)


@cli.command(short_help="Forcefully kill running server")
@click.argument("name")
@click.option("-f", "--force", is_flag=True, help="Force action without confirmation")
@configuration_present
def kill(name, force):
    """
    Forcefully kill running server

    NAME is the name of the server
    """

    if force or click.confirm(
        "Are you sure you want to do this? This will kill the running container without saving data."
    ):
        with Halo(text="Killing server", color="yellow", spinner="dots") as spinner:
            server = session.query(Server).filter_by(name=name.lower()).first()

            if not server:
                spinner.fail("Server does not exit")
                sys.exit(1)

            try:
                servers.kill(server)
                servers.set_status(server, "stopped")
                servers.sync()
            except Exception as e:
                spinner.fail()
                ui_exception(e)

            spinner.succeed("Server killed")


@cli.command(short_help="Stop server gracefully")
@click.argument("name")
@configuration_present
def stop(name):
    """
    Stop server gracefully.

    NAME is the name of the server
    """

    try:
        servers.sync()
    except Exception as e:
        ui_exception(e)

    with Halo(text="Stopping server", color="yellow", spinner="dots") as spinner:
        server = session.query(Server).filter_by(name=name.lower()).first()

        if not server:
            spinner.fail("Server does not exit")
            sys.exit(1)

        if server.status == "installing":
            spinner.fail(
                " ".join(
                    (
                        "Server is installing, you cannot gracefully stop it.",
                        "Use `wilfred kill` if the installation process has hanged.",
                    )
                )
            )
            sys.exit(1)

        try:
            servers.set_status(server, "stopped")
            servers.sync()
        except Exception as e:
            spinner.fail()
            ui_exception(e)

        spinner.succeed("Server stopped")


@cli.command(short_help="Restart server")
@click.argument("name")
@click.option(
    "--console", help="Attach to server console immediately after start.", is_flag=True
)
@click.pass_context
@configuration_present
def restart(ctx, name, console):
    """
    Restart server

    NAME is the name of the server
    """

    ctx.invoke(stop, name=name)
    ctx.invoke(start, name=name)

    if console:
        ctx.invoke(server_console, name=name)


@cli.command()
@click.argument("name")
@click.option("-f", "--force", is_flag=True, help="Force action without confirmation")
@configuration_present
def delete(name, force):
    """
    Delete existing server.

    NAME is the name of the server
    """

    if force or click.confirm(
        "Are you sure you want to do this? All data will be permanently deleted."
    ):
        with Halo(text="Deleting server", color="yellow", spinner="dots") as spinner:
            server = session.query(Server).filter_by(name=name.lower()).first()

            if not server:
                spinner.fail("Server does not exit")
                sys.exit(1)

            try:
                servers.remove(server)
                spinner.succeed("Server removed")
            except Exception as e:
                spinner.fail()
                ui_exception(e)


@cli.command("command", short_help="Send command to STDIN of server")
@click.argument("name")
@click.argument("command")
@configuration_present
def run_command(name, command):
    """
    Send command to STDIN of server

    \b
    NAME is the name of the server
    COMMAND is the command to send, can be put in \" for commands with whitespaces
    """

    server = session.query(Server).filter_by(name=name.lower()).first()

    if not server:
        error("Server does not exit", exit_code=1)

    try:
        servers.command(server, command)
    except Exception as e:
        ui_exception(e)


@cli.command(
    "console",
    short_help="\n\n".join(
        (
            " ".join(
                (
                    "Attach current terminal to the console of a specific server (STDIN of running process).",
                    "This allows you to view the current log and send commands.",
                )
            ),
            "Use CTRL+C to exit the console, the server will continue to run in the background.",
        )
    ),
)
@click.argument("name")
@configuration_present
def server_console(name):
    """
    Attach to server console, view log and run commands

    NAME is the name of the server
    """

    server = session.query(Server).filter_by(name=name.lower()).first()

    if not server:
        error("Server does not exit", exit_code=1)

    click.secho(
        " ".join(
            (
                f"Viewing server console of {name} (id {server.id})",
                f"{'- input disabled, installing' if server.status == 'installing' else ''}",
            )
        ),
        bold=True,
    )

    try:
        servers.console(
            server, disable_user_input=True if server.status == "installing" else False
        )
    except Exception as e:
        ui_exception(e)


@cli.command(
    short_help=" ".join(
        (
            "Edit existing server (name, memory, port, environment variables and the custom startup command).",
            "Restart server after update for changes to take effect.",
        )
    )
)
@click.argument("name")
@configuration_present
def edit(name):
    """
    Edit server (name, memory, port, environment variables)

    NAME is the name of the server
    """

    server = session.query(Server).filter_by(name=name.lower()).first()

    if not server:
        error("Server does not exist", exit_code=1)

    click.echo(
        pretty_list(
            [
                {
                    c.key: getattr(server, c.key)
                    for c in inspect(server).mapper.column_attrs
                }
            ],
            tablefmt="plain" if get_terminal_size((80, 20))[0] < 96 else "fancy_grid",
        )
    )
    click.echo("Leave values empty to use existing value")

    name = click.prompt("Name", default=server.name).lower()

    if " " in name:
        error("space not allowed in name", exit_code=1)

    port = click.prompt("Port", default=server.port)
    memory = click.prompt("Memory", default=server.memory)

    if not is_integer(port) or not is_integer(memory):
        error("port/memory must be integer", exit_code=1)

    click.secho("Environment Variables", bold=True)

    for v in images.get_image(server.image_uid)["variables"]:
        if v["install_only"]:
            continue

        current_variable = (
            session.query(EnvironmentVariable)
            .filter_by(server_id=server.id)
            .filter_by(variable=v["variable"])
            .first()
        )

        if not current_variable:
            continue

        if not v["hidden"]:
            value = click.prompt(v["prompt"], default=current_variable.value)

        if v["hidden"]:
            value = v["default"]

        current_variable.value = value

        try:
            session.commit()
        except IntegrityError as e:
            error(
                f"unable to edit variables {click.style(str(e), bold=True)}",
                exit_code=1,
            )

    server.custom_startup = (
        None if server.custom_startup == "None" else server.custom_startup
    )
    custom_startup = None

    if server.custom_startup is not None:
        custom_startup = click.prompt(
            "Custom startup command (use 'None' to reset to default)",
            default=server.custom_startup,
        )

    if server.custom_startup is None:
        if click.confirm("Would you like to set a custom startup command?"):
            custom_startup = click.prompt(
                "Custom startup command (use 'None' to reset to default)",
                default=images.get_image(server.image_uid)["command"],
            )

            custom_startup = None if custom_startup == "None" else custom_startup

    if name != server.name:
        try:
            servers.rename(server, name)
        except Exception as e:
            ui_exception(e)

    server.port = port
    server.memory = memory

    if custom_startup:
        server.custom_startup = custom_startup

    try:
        session.commit()
    except IntegrityError as e:
        error(f"unable to edit server {click.style(str(e), bold=True)}", exit_code=1)

    click.echo(
        "✅ Server information updated, restart server for changes to take effect"
    )


@cli.command(
    short_help=" ".join(("Show server statistics, CPU load, memory load etc.",))
)
def top():
    while True:
        # retrieve data (this can take a split moment)
        data = servers.all(cpu_load=True, memory_usage=True)

        for server in data:
            server.update(
                (
                    k,
                    str(v)
                    .replace("running", click.style("running", fg="green"))
                    .replace("stopped", click.style("stopped", fg="red"))
                    .replace("installing", click.style("installing", fg="yellow")),
                )
                for k, v in server.items()
            )

        # clear the screen
        click.clear()

        headers = {
            "id": click.style("ID", bold=True),
            "name": click.style("Name", bold=True),
            "image_uid": click.style("Image UID", bold=True),
            "memory": click.style("RAM", bold=True),
            "port": click.style("Port", bold=True),
            "status": click.style("Status", bold=True),
            "custom_startup": click.style("Custom startup", bold=True),
            "cpu_load": click.style("CPU", bold=True),
            "memory_usage": click.style("MEM usage / MEM %", bold=True),
        }

        # display table
        click.echo(
            tabulate(
                data,
                headers=headers,
                tablefmt="plain",
            )
        )

        # cooldown before repeating
        sleep(1)


@cli.command(
    "config",
    short_help="".join(
        (
            "View and edit configuration variables (e.g. the settings in `server.properties` for Minecraft).",
        )
    ),
)
@click.argument("name")
@click.argument("variable", required=False)
@click.argument("value", required=False)
def config_command(name, variable, value):
    """
    Manage server configuration (for supported filetypes)

    \b
    NAME is the name of the server
    VARIABLE is the name of an available setting
    VALUE is the new value for the variable setting
    """

    def _get():
        return ServerConfig(config.configuration, servers, server, image)

    def _print_all_values(variable, config_list):
        for var in config_list:
            click.echo(
                f"{click.style(var['_wilfred_config_filename'], bold=True)} {variable}: '{var[variable]}'"
            )

    def _get_variable_occurrences(variable, raw):
        _variable_occurrences = []
        for x in raw:
            if variable in x:
                _variable_occurrences.append(x)

        return _variable_occurrences

    server = session.query(Server).filter_by(name=name.lower()).first()

    if not server:
        error("Server does not exist", exit_code=1)

    image = images.get_image(server.image_uid)

    if not image:
        error("Image UID does not exit", exit_code=1)

    server_conf = _get()

    _variable_occurrences = _get_variable_occurrences(variable, server_conf.raw)

    if variable and len(_variable_occurrences) == 0:
        error("variable does not exist", exit_code=1)

    if variable and len(_variable_occurrences) > 1:
        click.echo("This variable exists in multiple configuration files.")

    if variable and not value:
        _print_all_values(variable, _variable_occurrences)
        exit(0)

    if variable and value:
        user_selection = None
        if len(_variable_occurrences) > 1:
            for i in range(len(_variable_occurrences)):
                click.echo(
                    f"[{i}] - {_variable_occurrences[i]['_wilfred_config_filename']}"
                )

            user_selection = click.prompt(
                "In which file would like to modify this setting?", default=0
            )

            if (
                int(user_selection) >= len(_variable_occurrences)
                or int(user_selection) < 0
            ):
                error(
                    "integer is not valid, please pick one from the list", exit_code=1
                )

        filename = _variable_occurrences[user_selection if user_selection else 0][
            "_wilfred_config_filename"
        ]

        try:
            server_conf.edit(filename, variable, value)
            server_conf = _get()
            _print_all_values(
                variable, _get_variable_occurrences(variable, server_conf.raw)
            )
        except Exception as e:
            ui_exception(e)

        exit(0)

    click.echo(server_conf.pretty())


@cli.command(
    "port",
    short_help="".join(("Manage additional ports for a server.",)),
)
@click.argument("name")
@click.argument("action", required=False)
@click.argument("port", required=False)
def port_command(name, action, port):
    """
    Manage additional ports for a server.

    \b
    NAME is the name of the server
    ACTION is the action, either "remove" or "add"
    PORT is the port to add or remove
    """

    server = session.query(Server).filter_by(name=name.lower()).first()

    if not server:
        error("Server does not exist", exit_code=1)

    if action == "add":
        if not is_integer(port):
            error("Port must be integer", exit_code=1)

        if len(session.query(Server).filter_by(port=port).all()) != 0:
            error("Port is already occupied by a server", exit_code=1)

        # create
        additional_port = Port(server_id=server.id, port=port)
        session.add(additional_port)

        try:
            session.commit()
        except IntegrityError as e:
            error(
                f"unable to create port {click.style(str(e), bold=True)}", exit_code=1
            )

    if action == "remove":
        additional_port = (
            session.query(Port).filter_by(port=port, server_id=server.id).first()
        )

        if not additional_port:
            error("Port not found", exit_code=1)

        session.delete(additional_port)
        session.commit()

    # display ports
    ports = [
        {"port": u.port}
        for u in session.query(Port).filter_by(server_id=server.id).all()
    ]
    click.echo(f"Additional ports for server {server.name}")
    click.echo(
        tabulate(
            ports,
            headers={
                "port": click.style("Port", bold=True),
            },
            tablefmt="fancy_grid",
        )
    )


if __name__ == "__main__":
    main()
