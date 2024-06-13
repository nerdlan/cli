#################################################################
#                                                               #
# Wilfred                                                       #
# Copyright (C) 2020-2022, Vilhelm Prytz, <vilhelm@prytznet.se> #
#                                                               #
# Licensed under the terms of the MIT license, see LICENSE.     #
# https://github.com/wilfred-dev/wilfred                        #
#                                                               #
#################################################################

import json

from appdirs import user_config_dir
from os.path import isfile, isdir
from pathlib import Path

from wilfred.api.errors import WilfredException, ParseError, WriteError

API_VERSION = 1


class NoConfiguration(WilfredException):
    """Configuration files does not exist"""


class ConfigurationAPIMismatch(WilfredException):
    """API level of config does not match with API level present in config"""


class Config(object):
    def __init__(self):
        self.data_dir = f"{user_config_dir()}/wilfred"
        self.config_path = f"{self.data_dir}/config.json"
        self.configuration = None

        if not isdir(self.data_dir):
            Path(self.data_dir).mkdir(parents=True, exist_ok=True)

    def read(self):
        if not isfile(self.config_path):
            raise NoConfiguration

        with open(self.config_path) as f:
            try:
                self.configuration = json.loads(f.read())
            except Exception as e:
                raise ParseError(e)

        if self.configuration["meta"]["version"] != API_VERSION:
            raise ConfigurationAPIMismatch(
                f"Wilfred has version {API_VERSION}, file has version {self.configuration['meta']['version']}"
            )

    def write(self, data_path):
        try:
            Path(data_path).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise WriteError(e)

        with open(self.config_path, "w") as f:
            f.write(
                json.dumps(
                    {"meta": {"version": API_VERSION}, "data_path": data_path}, indent=4
                )
            )
