####################################################################
#                                                                  #
# Wilfred                                                          #
# Copyright (C) 2020, Vilhelm Prytz, <vilhelm@prytznet.se>, et al. #
#                                                                  #
# Licensed under the terms of the MIT license, see LICENSE.        #
# https://github.com/wilfred-dev/wilfred                           #
#                                                                  #
####################################################################

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
from copy import deepcopy

API_VERSION = 2


class ImagesNotPresent(Exception):
    """Default images not present on host"""

    pass


class ImagesNotRead(Exception):
    """Images are not read yet"""

    pass


class ReadError(Exception):
    """Unable to read certain files"""

    pass


class ParseError(Exception):
    """Image format is incorrect"""

    pass


class ImageAPIMismatch(Exception):
    """API level of image and API level of Wilfred mismatch"""

    pass


class Images(object):
    def __init__(self):
        self.config_dir = f"{user_config_dir()}/wilfred"
        self.image_dir = f"{self.config_dir}/images"
        self.images = []

        if not isdir(self.image_dir):
            Path(self.image_dir).mkdir(parents=True, exist_ok=True)

    def download(self):
        rmtree(f"{self.image_dir}/default", ignore_errors=True)

        with open(f"{self.config_dir}/img.zip", "wb") as f:
            response = get(
                "https://github.com/wilfred-dev/images/archive/master.zip", stream=True,
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

    def pretty(self):
        if not self._check_if_read():
            raise ImagesNotRead("Read images before trying to get images")

        _images = deepcopy(self.images)

        for d in _images:
            for key in (
                "meta",
                "installation",
                "docker_image",
                "command",
                "stop_command",
                "variables",
                "user",
                "config",
            ):
                try:
                    del d[key]
                except Exception:
                    pass

        headers = {
            "uid": click.style("UID", bold=True),
            "name": click.style("Image Name", bold=True),
            "author": click.style("Author", bold=True),
            "default_image": click.style("Default Image", bold=True),
        }

        return tabulate(_images, headers=headers, tablefmt="fancy_grid")

    def get_image(self, uid):
        if not self._check_if_read():
            raise ImagesNotRead("Read images before trying to get image")

        return next(filter(lambda img: img["uid"] == uid, self.images), None)

    def read_images(self):
        if not self.check_if_present():
            raise ImagesNotPresent("Default images not present")

        self.images = []

        for root, dirs, files in walk(self.image_dir):
            for file in files:
                if file.endswith(".json"):
                    with open(join(root, file)) as f:
                        try:
                            _image = json.loads(f.read())
                        except Exception as e:
                            raise ReadError(f"{file} failed with exception {str(e)}")

                        try:
                            if _image["meta"]["api_version"] != API_VERSION:
                                raise ImageAPIMismatch(
                                    " ".join(
                                        (
                                            f"{file} API level {_image['meta']['api_version']},",
                                            f"Wilfred API level {API_VERSION}",
                                        )
                                    )
                                )
                        except ImageAPIMismatch as e:
                            raise ImageAPIMismatch(str(e))
                        except Exception as e:
                            raise ReadError(f"{file} with err {str(e)}")

                        self._verify(_image, file)
                        self.images.append(_image)

        return True

    def check_if_present(self):
        if not isdir(f"{self.image_dir}/default"):
            return False

        return True

    def _verify(self, image, file):
        def _exception(key):
            raise ParseError(f"image {file} is missing key {str(key)}")

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
            "config",
        ):
            try:
                image[key]
            except Exception:
                return _exception(key)

        if image["uid"] != image["uid"].lower():
            raise ParseError(f"image {file} uid must be lowercase")

        for key in ["api_version"]:
            try:
                image["meta"][key]
            except Exception:
                return _exception(key)

        for key in ("docker_image", "shell", "script"):
            try:
                image["installation"][key]
            except Exception:
                return _exception(key)

        try:
            image["config"]["files"]
        except Exception:
            return _exception(key)

        if len(image["config"]["files"]) > 0:
            for i in range(len(image["config"]["files"])):
                for key in ("filename", "parser", "environment", "action"):
                    try:
                        image["config"]["files"][i][key]
                    except Exception:
                        return _exception(key)

                # check for valid syntax in environment variables
                for x in range(len(image["config"]["files"][i]["environment"])):
                    for key in (
                        "config_variable",
                        "environment_variable",
                        "value_format",
                    ):
                        try:
                            image["config"]["files"][i]["environment"][x][key]
                        except Exception:
                            return _exception(
                                f"{image['config']['files'][i]['filename']} environment key {key}"
                            )

            # should also check for valid syntax in environment variable linking

        if len(image["variables"]) > 0:
            for i in range(len(image["variables"])):
                for key in ("prompt", "variable", "install_only", "default", "hidden"):
                    try:
                        image["variables"][i][key]
                    except Exception:
                        return _exception(key)

        return True

    def _check_if_read(self):
        if len(self.images) == 0:
            return False

        return True
