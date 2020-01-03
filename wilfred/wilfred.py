# -*- coding: utf-8 -*-

# wilfred
# https://github.com/wilfred-dev/wilfred
# (c) Vilhelm Prytz 2020

import click
import codecs
import subprocess
import locale
import os
import sys

from yaspin import yaspin

from wilfred.docker_conn import docker_client
from wilfred.version import version
from wilfred.config_parser import Config
from wilfred.database import Database
from wilfred.servers import Servers
from wilfred.images import Images
from wilfred.message_handler import warning, error

config = Config()
database = Database()
images = Images()
servers = Servers(database, docker_client(), config.configuration, images)


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo("✨ wilfred version {}".format(version))
    ctx.exit()


def main():
    # If the locale ends up being ascii, Click will barf. Let's try to prevent that
    # here by using C.UTF-8 as a last-resort fallback. This mostly happens in CI,
    # using LXD or Docker. This is the same logic used by Click to error out.
    if (
        codecs.lookup(locale.getpreferredencoding()).name == "ascii"
        and os.name == "posix"
    ):
        output = subprocess.check_output(["locale", "-a"]).decode("ascii", "replace")

        for line in output.splitlines():
            this_locale = line.strip()
            if this_locale.lower() in ("c.utf8", "c.utf-8"):
                warning("Locale not set! Wilfred will temporarily use C.UTF-8")
                os.environ["LC_ALL"] = "C.UTF-8"
                os.environ["LANG"] = "C.UTF-8"
                break

    cli()


@click.group()
@click.option(
    "--version", is_flag=True, callback=print_version, expose_value=False, is_eager=True
)
def cli():
    """
    🐿️  A CLI for managing game servers using Docker.

    ⚠️  Wilfred is currently under development and should not be considered stable.
    Features may brake or may not beimplemented yet. Use with caution.
    """

    pass


@cli.command()
def setup():
    """setup wilfred, create config"""

    if config.configuration:
        warning("A configuration file for Wilfred already exists.")
        click.confirm("Are you sure you wan't to continue?", abort=True)

    data_path = click.prompt(
        "Path for storing server data", default="/srv/wilfred/servers"
    )

    config.write(data_path)


@cli.command("servers")
def servers_list():
    """list of all servers"""

    click.echo(servers.pretty())


@cli.command("images")
def list_images():
    """list available images"""

    click.echo(images.pretty())


@cli.command()
@click.option(
    "--console",
    help="Attach to server console immediately after creation.",
    is_flag=True,
)
@click.pass_context
def create(ctx, console):
    """create a new server"""

    if not config.configuration:
        error("Wilfred has not been configured", exit_code=1)

    click.secho("Available Images", bold=True)
    click.echo(images.pretty())

    name = click.prompt("Name").lower()
    image_uuid = click.prompt("Image UUID", default="default-vanilla-minecraft")
    port = click.prompt("Port", default=25565)
    memory = click.prompt("Memory", default=1024)

    if " " in name:
        error("space not allowed in name", exit_code=1)

    if " " in image_uuid:
        error("space not allowed in image_uuid", exit_code=1)

    if not images.get_image(image_uuid):
        error("image does not exist", exit_code=1)

    with yaspin(text="Creating server", color="yellow") as spinner:
        servers.create(name, image_uuid, memory, port)

        spinner.ok("✅ ")

    if console:
        ctx.invoke(server_console, name=name)


@cli.command("sync")
def sync_cmd():
    """
    sync all servers on file with Docker (start/kill/create)
    """

    with yaspin(text="Docker sync", color="yellow") as spinner:
        if not config.configuration:
            spinner.fail("💥 Wilfred has not been configured")

        servers.sync()

        spinner.ok("✅ ")


@cli.command()
@click.argument("name")
@click.option(
    "--console", help="Attach to server console immediately after start.", is_flag=True
)
@click.pass_context
def start(ctx, name, console):
    """
    start existing server
    """

    with yaspin(text="Server start", color="yellow") as spinner:
        if not config.configuration:
            spinner.fail("💥 Wilfred has not been configured")
            sys.exit(1)

        server = servers.get_by_name(name.lower())

        if not server:
            spinner.fail("💥 Server does not exit")
            sys.exit(1)

        servers.set_status(server[0], "running")
        servers.sync()

        spinner.ok("✅ ")

        if console:
            ctx.invoke(server_console, name=name)


@cli.command()
@click.argument("name")
def kill(name):
    """
    kill running server
    """

    with yaspin(text="Killing server", color="yellow") as spinner:
        if not config.configuration:
            spinner.fail("💥 Wilfred has not been configured")
            sys.exit(1)

        server = servers.get_by_name(name.lower())

        if not server:
            spinner.fail("💥 Server does not exit")
            sys.exit(1)

        servers.set_status(server[0], "stopped")
        servers.sync()

        spinner.ok("✅ ")


@cli.command()
@click.argument("name")
def delete(name):
    """delete existing server"""

    if click.confirm(
        "Are you sure you want to do this? All data will be permanently deleted."
    ):
        with yaspin(text="Deleting server", color="yellow") as spinner:
            if not config.configuration:
                spinner.fail("💥 Wilfred has not been configured")
                sys.exit(1)

            server = servers.get_by_name(name.lower())

            if not server:
                spinner.fail("💥 Server does not exit")
                sys.exit(1)

            servers.remove(server[0])
            spinner.ok("✅ ")


@cli.command("console")
@click.argument("name")
def server_console(name):
    """view log and run commands"""

    if not config.configuration:
        error("Wilfred has not been configured", exit_code=1)

    server = servers.get_by_name(name.lower())

    if not server:
        error("Server does not exit", exit_code=1)

    servers.console(server[0])


if __name__ == "__main__":
    main()
