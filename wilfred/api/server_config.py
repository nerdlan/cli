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

from tabulate import tabulate

from wilfred.container_variables import ContainerVariables
from wilfred.api.errors import WilfredException, ParseError, WriteError

from wilfred.api.parser.properties import properties_read, properties_write
from wilfred.api.parser.yaml import yaml_read, yaml_write
from wilfred.api.parser.json import json_read, json_write


class UnsupportedFiletype(WilfredException):
    """File type is not supported by parser"""


class ServerConfig:
    def __init__(self, configuration, servers, server, image):
        """
        Read, edit and update configurations for servers. Exposes server specific configs to Wilfred.

        :param configuration: JSON dict for Wilfred config
        :param object servers: wilfred.api.servers object
        :param str server: SQLAlchemy server object
        :param dictionary image: Image dict object
        """

        self._configuration = configuration
        self._servers = servers
        self._server = server
        self._image = image

        self.raw = []
        self._variables = []  # list of dicts

        self._parse()

    def _parse(self):
        """iterates configuration files for the specific server and parses the files"""

        def _err(e):
            raise ParseError(f"failed to parse {file['filename']}, err {str(e)}")

        for file in self._image["config"]["files"]:
            path = f"{self._configuration['data_path']}/{self._server.name}_{self._server.id}/{file['filename']}"

            if file["parser"] == "properties":
                try:
                    _raw = properties_read(path)
                except Exception as e:
                    _err(e)

                _raw["_wilfred_config_filename"] = file["filename"]
                self.raw.append(_raw)

                continue

            if file["parser"] == "yaml":
                try:
                    _raw = yaml_read(path)
                except Exception as e:
                    _err(e)

                _raw["_wilfred_config_filename"] = file["filename"]
                self.raw.append(_raw)

                continue

            if file["parser"] == "json":
                try:
                    _raw = json_read(path)
                except Exception as e:
                    _err(e)

                _raw["_wilfred_config_filename"] = file["filename"]
                self.raw.append(_raw)

                continue

            raise UnsupportedFiletype(file["parser"])
        return True

    def pretty(self):
        """returns parsed configuration variables in a print-friendly format"""

        headers = {
            "file": click.style("Config File", bold=True),
            "setting": click.style("Setting", bold=True),
            "value": click.style("Value", bold=True),
        }

        data = []

        for file in self.raw:
            for k, v in file.items():
                for _image_config_file in self._image["config"]["files"]:
                    for x in _image_config_file["environment"]:
                        k = (
                            f"{k} ({click.style('not editable', fg='red', bold=True)})"
                            if x["config_variable"] == k
                            else k
                        )

                data.append(
                    {"file": file["_wilfred_config_filename"], "setting": k, "value": v}
                ) if k != "_wilfred_config_filename" else None

        return tabulate(
            data,
            headers=headers,
            tablefmt="fancy_grid",
        )

    def edit(self, filename, variable, value, override_linking_check=False):
        """modifies value of specified variable"""

        try:
            value = int(value)
        except Exception:
            pass

        try:
            value = True if value.lower() == "true" else value
            value = False if value.lower() == "false" else value
        except Exception:
            pass

        for file in self._image["config"]["files"]:
            if file["filename"] == filename:
                path = f"{self._configuration['data_path']}/{self._server.name}_{self._server.id}"

                for _image_config_file in self._image["config"]["files"]:
                    for x in _image_config_file["environment"]:
                        if (
                            x["config_variable"] == variable
                            and not override_linking_check
                        ):
                            raise WriteError(
                                "This setting is linked to an environment variable and is therefore not editable directly"
                            )

                if file["parser"] == "properties":
                    properties_write(f"{path}/{file['filename']}", variable, value)

                if file["parser"] == "yaml":
                    yaml_write(f"{path}/{file['filename']}", variable, value)

                if file["parser"] == "json":
                    json_write(f"{path}/{file['filename']}", variable, value)

                if variable in file["action"]:
                    self._servers.command(
                        self._server, file["action"][variable].format(value)
                    )

    def write_environment_variables(self):
        """writes environment variable to config file(s)"""

        for file in self._image["config"]["files"]:
            for _env in file["environment"]:
                env_vars = ContainerVariables(self._server, self._image).get_env_vars()

                if _env["environment_variable"] in env_vars:
                    self.edit(
                        file["filename"],
                        _env["config_variable"],
                        _env["value_format"].format(
                            env_vars[_env["environment_variable"]]
                        )
                        if _env["value_format"]
                        else env_vars[_env["environment_variable"]],
                        override_linking_check=True,
                    )
