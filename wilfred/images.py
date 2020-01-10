# Wilfred
# Copyright (C) 2020, Vilhelm Prytz, <vilhelm@prytznet.se>
#
# Licensed under the terms of the MIT license, see LICENSE.
# https://github.com/wilfred-dev/wilfred

import json
import click

from tabulate import tabulate
from appdirs import user_config_dir
from pathlib import Path
from os.path import isdir, join
from os import walk, remove
from requests import get
from zipfile import ZipFile
from shutil import move, rmtree

from wilfred.message_handler import warning, error

API_VERSION = 0


class Images(object):
    def __init__(self):
        self.config_dir = f"{user_config_dir()}/wilfred"
        self.image_dir = f"{self.config_dir}/images"

        if not isdir(self.image_dir):
            Path(self.image_dir).mkdir(parents=True, exist_ok=True)

        if not isdir(f"{self.image_dir}/default"):
            warning(
                "default image directory does not exist, downloading default images"
            )
            self.download_default()

        if not self._read_images():
            self.download_default()
            if not self._read_images(silent=True):
                error(
                    "Image still has incorrect API version after refresh", exit_code=1
                )
            click.echo("✅ Solved after default images refresh")

    def download_default(self, read=False):
        rmtree(f"{self.image_dir}/default", ignore_errors=True)

        with open(f"{self.config_dir}/img.zip", "wb") as f:
            response = get(
                "https://github.com/wilfred-dev/images/archive/master.zip", stream=True
            )
            f.write(response.content)

        with ZipFile(f"{self.config_dir}/img.zip", "r") as obj:
            obj.extractall(f"{self.config_dir}/temp_images")

        move(
            f"{self.config_dir}/temp_images/images-master/images",
            f"{self.image_dir}/default",
        )

        remove(f"{self.config_dir}/img.zip")
        rmtree(f"{self.config_dir}/temp_images")

        if read:
            self._read_images()

    def pretty(self):
        _images = self.images

        for d in _images:
            for key in (
                "meta",
                "installation",
                "docker_image",
                "command",
                "stop_command",
                "variables",
                "user",
            ):
                try:
                    del d[key]
                except Exception:
                    pass

        headers = {
            "uid": "UID",
            "name": "Image Name",
            "author": "Author",
            "default_image": "Default Image",
        }

        return tabulate(_images, headers=headers, tablefmt="fancy_grid")

    def get_image(self, uid):
        self._read_images()

        image = list(filter(lambda img: img["uid"] == uid, self.images))

        return image[0] if image else None

    def _verify(self, image, file):
        def _exception(key):
            error(f"image {file} is missing key {str(key)}", exit_code=1)

        for key in (
            "meta",
            "uid",
            "name",
            "author",
            "docker_image",
            "command",
            "user",
            "stop_command",
            "default_image",
            "variables",
            "installation",
        ):
            try:
                image[key]
            except Exception:
                _exception(key)

        for key in ["api_version"]:
            try:
                image["meta"][key]
            except Exception:
                _exception(key)

        for key in ("docker_image", "shell", "script"):
            try:
                image["installation"][key]
            except Exception:
                _exception(key)

    def _read_images(self, silent=False):
        self.images = []

        for root, dirs, files in walk(self.image_dir):
            for file in files:
                if file.endswith(".json"):
                    with open(join(root, file)) as f:
                        try:
                            _image = json.loads(f.read())
                        except Exception as e:
                            error(
                                f"unable to parse {file} with error {click.style(str(e), bold=True)}",
                                exit_code=1,
                            )

                        try:
                            if _image["meta"]["api_version"] != API_VERSION:
                                if not silent:
                                    warning(
                                        " ".join(
                                            (
                                                f"{file} image has API level {_image['meta']['api_version']},",
                                                f"Wilfreds API level is {API_VERSION}",
                                            )
                                        )
                                    )
                                return False
                        except Exception as e:
                            if not silent:
                                error(
                                    " ".join(
                                        (
                                            f"could not parse config for image {file},",
                                            f"has API level changed? - {click.style(str(e), bold=True)}",
                                        )
                                    )
                                )
                            return False

                        self._verify(_image, file)
                        self.images.append(_image)

        return True
