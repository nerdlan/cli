#################################################################
#                                                               #
# Wilfred                                                       #
# Copyright (C) 2020-2022, Vilhelm Prytz, <vilhelm@prytznet.se> #
#                                                               #
# Licensed under the terms of the MIT license, see LICENSE.     #
# https://github.com/wilfred-dev/wilfred                        #
#                                                               #
#################################################################

from wilfred.api.database import session, EnvironmentVariable


class ContainerVariables(object):
    def __init__(self, server, image, install=False):
        self._server = server
        self._image = image
        self._install = install

    def parse_startup_command(self, cmd):
        for k, v in self.get_env_vars().items():
            cmd = cmd.replace("{{image.env." + str(k) + "}}", str(v if v else ""))

        return cmd

    def get_env_vars(self):
        environment = {}

        for var in self._image["variables"]:
            value = (
                session.query(EnvironmentVariable)
                .filter_by(server_id=self._server.id)
                .filter_by(variable=var["variable"])
                .first()
                .value
            )

            if var["install_only"] and not self._install:
                continue

            environment[var["variable"]] = value

        environment["SERVER_MEMORY"] = self._server.memory
        environment["SERVER_PORT"] = self._server.port

        return environment
