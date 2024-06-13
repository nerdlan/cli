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
import docker

from pathlib import Path
from shutil import rmtree
from os import remove as remove_file
from os import rename
from time import sleep
from sys import platform
from subprocess import call
from sqlalchemy import inspect

from wilfred.api.database import session, Server, EnvironmentVariable, Port
from wilfred.keyboard import KeyboardThread
from wilfred.container_variables import ContainerVariables
from wilfred.api.images import Images
from wilfred.api.errors import WilfredException, WriteError
from wilfred.core import random_string


class ServerNotRunning(WilfredException):
    """Server is not running"""


class ServerNotFound(WilfredException):
    """Specified server was not found"""


class Servers(object):
    def __init__(
        self, docker_client: docker.DockerClient, configuration: dict, images: Images
    ):
        """
        Initiates wilfred.api.Servers, method for controlling servers

        Args:
            docker_client (docker.DockerClient): DockerClient object from Docker module
            configuration (dict): Dictionary of Wilfred config
            images (Images): wilfred.api.Images object
        """

        self._images = images
        self._configuration = configuration
        self._docker_client = docker_client

    def all(self, cpu_load=False, memory_usage=False):
        """
        Returns data of all servers

        Args:
            cpu_load (bool): Include the CPU load of the container. Defaults to `None` if server is not running.
            memory_usage (bool): Include memory usage of the container. Defaults to `None` if server is not running.
        """

        servers = [
            {c.key: getattr(u, c.key) for c in inspect(u).mapper.column_attrs}
            for u in session.query(Server).all()
        ]

        for server in servers:
            if cpu_load or memory_usage:
                for server in servers:
                    _running = True
                    _stats_avail = True

                    try:
                        container = self._docker_client.containers.get(
                            f"wilfred_{server['id']}"
                        )
                        d = container.stats(stream=False)
                    except docker.errors.NotFound:
                        server.update({"cpu_load": "-"})
                        server.update({"memory_usage": "-"})
                        _running = False
                    except Exception:
                        server.update({"cpu_load": "error"})
                        server.update({"memory_usage": "error"})
                        _running = False

                    if cpu_load and _running:
                        # on some systems, statisics are not available
                        if (
                            "system_cpu_usage" not in d["cpu_stats"]
                            or "system_cpu_usage" not in d["precpu_stats"]
                        ):
                            server.update({"cpu_load": "-"})
                            _stats_avail = False

                    if cpu_load and _running and _stats_avail:
                        # calculate the change in CPU usage between current and previous reading
                        cpu_delta = float(
                            d["cpu_stats"]["cpu_usage"]["total_usage"]
                        ) - float(d["precpu_stats"]["cpu_usage"]["total_usage"])

                        # calculate the change in system CPU usage between current and previous reading
                        system_delta = float(
                            d["cpu_stats"]["system_cpu_usage"]
                        ) - float(d["precpu_stats"]["system_cpu_usage"])

                        # Calculate number of CPU cores
                        cpu_count = float(d["cpu_stats"]["online_cpus"])
                        if cpu_count == 0.0:
                            cpu_count = len(
                                d["precpu_stats"]["cpu_usage"]["percpu_usage"]
                            )

                        if system_delta > 0.0:
                            cpu_percent = f"{round(cpu_delta / system_delta * 100.0 * cpu_count, 2)}%"

                        server.update({"cpu_load": cpu_percent if cpu_percent else "-"})

                    if memory_usage and _running:
                        mem_used = d["memory_stats"]["usage"] / 1024 / 1024
                        mem_percent = (
                            d["memory_stats"]["usage"]
                            / d["memory_stats"]["limit"]
                            * 100
                        )
                        server.update(
                            {
                                "memory_usage": f"{round(mem_used, 1)} MB / {round(mem_percent, 2)}%"
                            }
                        )

        return servers

    def set_status(self, server, status):
        server.status = status
        session.commit()

    def sync(self):
        """
        Performs sync, checks for state of containers
        """

        for server in session.query(Server).all():
            if server.status == "installing":
                try:
                    self._docker_client.containers.get(f"wilfred_{server.id}")
                except docker.errors.NotFound:
                    self.set_status(server, "stopped")

            # stopped
            if server.status == "stopped":
                self._stop(server)

            # start
            if server.status == "running":
                try:
                    self._docker_client.containers.get(f"wilfred_{server.id}")
                except docker.errors.NotFound:
                    self._start(server)

    def remove(self, server: Server):
        """
        Removes specified server

        Args:
            server (wilfred.api.database.Server): Server database object
        """

        path = f"{self._configuration['data_path']}/{server.name}_{server.id}"

        # delete all environment variables associated to this server
        for x in (
            session.query(EnvironmentVariable).filter_by(server_id=server.id).all()
        ):
            session.delete(x)

        # delete all additional ports associated to this server
        for x in session.query(Port).filter_by(server_id=server.id).all():
            session.delete(x)

        session.delete(server)
        session.commit()

        try:
            container = self._docker_client.containers.get(f"wilfred_{server.id}")
            container.kill()
        except docker.errors.NotFound:
            pass

        rmtree(path, ignore_errors=True)

    def console(self, server: Server, disable_user_input=False):
        """
        Enters server console

        Args:
            server (wilfred.api.database.Server): Server database object
            disable_user_input (bool): Blocks user input if `True`. By default this is `False`.

        Raises:
            :py:class:`ServerNotRunning`
                If server is not running
        """

        try:
            container = self._docker_client.containers.get(f"wilfred_{server.id}")
        except docker.errors.NotFound:
            raise ServerNotRunning(f"server {server.id} is not running")

        if platform.startswith("win"):
            click.echo(container.logs())
            call(["docker", "attach", container.id])
        else:
            if not disable_user_input:
                KeyboardThread(self._console_input_callback, params=server)

            try:
                for line in container.logs(stream=True, tail=200):
                    click.echo(line.strip())
            except docker.errors.NotFound:
                raise ServerNotRunning(f"server {server.id} is not running")

    def create(
        self,
        name,
        image_uid,
        memory,
        port,
        custom_startup=None,
        environment_variables=[],
        id=None,
    ):
        """
        Creates a new server

        Args:
            name (str): Name of new server
            image_uid (str): UID of server image to use
            memory (int): Memory to configure server with (in megabytes, i.e. 1024)
            port (int): Port server should listen to
            custom_startup (str, optional): Optional custom startup command (by default uses image command)
            environment_variables (:obj:`list` of :obj:`dict`, optional): Optional list of environment variables
            id (str, optional): Override generating random string as id by specifying it here

        Returns:
            wilfred.api.database.Server: Server database object of newly created server
        """

        server = Server(id=random_string() if not id else id)

        server.name = name
        server.image_uid = image_uid
        server.memory = memory
        server.port = port
        server.custom_startup = custom_startup
        server.status = "installing"

        # commit changes to database
        session.add(server)
        session.commit()

        for environment_variable in environment_variables:
            session.add(
                EnvironmentVariable(
                    server_id=server.id,
                    variable=environment_variable["variable"],
                    value=environment_variable["value"],
                )
            )

        session.commit()

        return server

    def query(self, name):
        """
        Returns :class:`wilfred.api.database.Server` object of specified server

        Args:
            name (str): Name of server to query for

        Returns:
            wilfred.api.database.Server: Server database object of specified server
        """

        server = session.query(Server).filter_by(name=name.lower()).first()

        if not server:
            raise ServerNotFound(f"Could not find server by name {name}")

        return server

    def install(self, server: Server, skip_wait=False, spinner=None):
        """
        Performs installation

        Args:
            server (wilfred.api.database.Server): Server database object
            skip_wait (bool): Doesn't stall while waiting for server installation to complete if `True`.
            spinner (Halo): If `Halo` spinner object is defined, will then write and perform actions to it.

        Raises:
            :py:class:`WriteError`
                If not able to create directory or write to it
        """

        path = f"{self._configuration['data_path']}/{server.name}_{server.id}"
        image = self._images.get_image(server.image_uid)

        if platform.startswith("win"):
            path = path.replace("/", "\\")

        try:
            Path(path).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise WriteError(f"could not create server data directory, {str(e)}")

        with open(f"{path}/install.sh", "w", newline="\n") as f:
            f.write("cd /server\n" + "\n".join(image["installation"]["script"]))

        if spinner:
            spinner.info(
                "Pulling Docker image and creating installation container, do not exit"
            )
            spinner.start()

        self._docker_client.containers.run(
            image["installation"]["docker_image"],
            f"{image['installation']['shell']} /server/install.sh",
            volumes={path: {"bind": "/server", "mode": "rw"}},
            name=f"wilfred_{server.id}",
            environment=ContainerVariables(server, image, install=True).get_env_vars(),
            remove=True,
            detach=True,
        )

        if skip_wait and spinner:
            spinner.info(
                "Installation will continue in background, use `wilfred servers` to see if process has finished."
            )
            spinner.start()

        if not skip_wait:
            if spinner:
                spinner.info(
                    "You can safely press CTRL+C, the installation will continue in the background."
                )
                spinner.info(
                    "Run `wilfred servers` to see when the status changes from `installing` to `stopped`."
                )
                spinner.info(
                    f"You can also follow the installation log using `wilfred console {server.name}`"
                )
                spinner.start()
            while self._container_alive(server):
                sleep(1)

    def kill(self, server):
        """
        Kills server container

        Args:
            server (wilfred.api.database.Server): Server database object

        Raises:
            :py:class:`ServerNotRunning`
                If server is not running
        """

        try:
            container = self._docker_client.containers.get(f"wilfred_{server.id}")
        except docker.errors.NotFound:
            raise ServerNotRunning(f"server {server.id} is not running")

        container.kill()

    def rename(self, server, name):
        """
        Renames server and moves server folder

        Args:
            server (wilfred.api.database.Server): Server database object
            name (str): New name of the server

        Raises:
            :py:class:`WilfredException`
                If server is running
            :py:class:`WriteError`
                If not able to move folder
        """

        if self._container_alive(server):
            raise WilfredException("You cannot rename the server while it is running")

        try:
            rename(
                f"{self._configuration['data_path']}/{server.name}_{server.id}",
                f"{self._configuration['data_path']}/{name}_{server.id}",
            )
        except Exception as e:
            raise WriteError(f"could not rename folder, {str(e)}")

        server.name = name
        session.commit()

    def _console_input_callback(self, payload, server):
        self.command(server, payload)

    def command(self, server, command):
        """
        Sends command to server console

        Args:
            server (wilfred.api.database.Server): Server database object
            command (str): The command to send to the stdin of the server

        Raises:
            :py:class:`ServerNotRunning`
                If server is not running
        """

        _cmd = f"{command}\n".encode("utf-8")

        try:
            container = self._docker_client.containers.get(f"wilfred_{server.id}")
        except docker.errors.NotFound:
            raise ServerNotRunning(f"server {server.id} is not running")

        s = container.attach_socket(params={"stdin": 1, "stream": 1})
        s.send(_cmd) if platform.startswith("win") else s._sock.send(_cmd)
        s.close()

    def _running_docker_sync(self):
        for server in session.query(Server).all():
            try:
                self._docker_client.containers.get(f"wilfred_{server.id}")
            except docker.errors.NotFound:
                self.set_status(server, "stopped")

    def _parse_startup_command(self, cmd, server, image):
        return ContainerVariables(server, image).parse_startup_command(
            cmd.replace("{{SERVER_MEMORY}}", str(server.memory)).replace(
                "{{SERVER_PORT}}", str(server.port)
            )
        )

    def _container_alive(self, server):
        try:
            self._docker_client.containers.get(f"wilfred_{server.id}")
        except docker.errors.NotFound:
            return False

        return True

    def _start(self, server):
        path = f"{self._configuration['data_path']}/{server.name}_{server.id}"
        image = self._images.get_image(server.image_uid)

        try:
            remove_file(f"{path}/install.sh")
        except Exception:
            pass

        # get additional ports
        ports = session.query(Port).filter_by(server_id=server.id).all()

        self._docker_client.containers.run(
            image["docker_image"],
            self._parse_startup_command(server.custom_startup, server, image)
            if server.custom_startup is not None
            else f"{self._parse_startup_command(image['command'], server, image)}",
            volumes={path: {"bind": "/server", "mode": "rw"}},
            name=f"wilfred_{server.id}",
            remove=True,
            ports={
                **{
                    f"{server.port}/tcp": server.port,
                    f"{server.port}/udp": server.port,
                },
                **{
                    f"{additional_port.port}/tcp": additional_port.port
                    for additional_port in ports
                },
                **{
                    f"{additional_port.port}/udp": additional_port.port
                    for additional_port in ports
                },
            },
            detach=True,
            working_dir="/server",
            mem_limit=f"{server.memory}m",
            oom_kill_disable=True,
            stdin_open=True,
            environment=ContainerVariables(server, image).get_env_vars(),
            user=image["user"] if image["user"] else "root",
        )

    def _stop(self, server):
        image = self._images.get_image(server.image_uid)

        try:
            container = self._docker_client.containers.get(f"wilfred_{server.id}")
        except docker.errors.NotFound:
            return

        if not image["stop_command"]:
            container.stop()

            return

        self.command(server, image["stop_command"])

        stopped = False

        while not stopped:
            try:
                self._docker_client.containers.get(f"wilfred_{server.id}")
            except docker.errors.NotFound:
                stopped = True
