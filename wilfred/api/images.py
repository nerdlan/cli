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
from pathlib import Path
from os.path import isdir, join, isfile
from os import walk, remove
from requests import get
from zipfile import ZipFile
from shutil import move, rmtree
from copy import deepcopy
from datetime import datetime, timedelta

from wilfred.api.errors import WilfredException, ReadError, ParseError
from wilfred.version import version

API_VERSION = 2


class ImagesNotPresent(WilfredException):
    """Default images not present on host"""


class ImagesNotRead(WilfredException):
    """Images are not read yet"""


class ImageAPIMismatch(WilfredException):
    """API level of image and API level of Wilfred mismatch"""


class ImagesOutdated(WilfredException):
    """Wilfred images are outdated and require refresh"""


class Images(object):
    """Manage Wilfred images"""

    def __init__(self):
        self.config_dir = f"{user_config_dir()}/wilfred"
        self.image_dir = f"{self.config_dir}/images"
        self.images = []

        if not isdir(self.image_dir):
            Path(self.image_dir).mkdir(parents=True, exist_ok=True)

    def download(self, branch="master", repo="wilfred-dev/images"):
        """
        Downloads default Wilfred Images from GitHub
        """

        rmtree(f"{self.image_dir}/default", ignore_errors=True)

        with open(f"{self.config_dir}/img.zip", "wb") as f:
            response = get(
                f"https://github.com/{repo}/archive/{branch}.zip",
                stream=True,
            )
            f.write(response.content)

        with ZipFile(f"{self.config_dir}/img.zip", "r") as obj:
            obj.extractall(f"{self.config_dir}/temp_images")

        move(
            f"{self.config_dir}/temp_images/images-{branch}/images",
            f"{self.image_dir}/default",
        )

        remove(f"{self.config_dir}/img.zip")
        rmtree(f"{self.config_dir}/temp_images")

        # write to cache info that images have been updated
        data = {"time": str(datetime.now()), "version": version}

        with open(f"{self.config_dir}/image_cache.json", "w") as f:
            json.dump(data, f)

    def data_strip_non_ui(self):
        """
        Returns a list of all images with only the variables important to the user shown

        Returns:
            Returns ``list`` of images.

        Raises:
            :py:class:`wilfred.api.images.ImagesNotRead`
        """

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

        return _images

    def get_image(self, uid: str):
        """
        Retrieves image configuration for specific image

        Returns:
            Returns ``dict`` of image configuration.

        Raises:
            :py:class:`wilfred.api.images.ImagesNotRead`
        """

        if not self._check_if_read():
            raise ImagesNotRead("Read images before trying to get image")

        return next(filter(lambda img: img["uid"] == uid, self.images), None)

    def read_images(self):
        """
        Reads and parses all images on system

        Returns:
            Returns ``True`` if success.

        Raises:
            :py:class:`wilfred.api.images.ImagesNotPresent`
            :py:class:`wilfred.api.errors.ReadError`
            :py:class:`wilfred.api.images.ImageAPIMismatch`
        """

        if not self.check_if_present():
            raise ImagesNotPresent("Default images not present")

        if self.is_outdated():
            raise ImagesOutdated("Images are outdated, refresh required")

        self.image_fetch_date = "N/A"
        self.image_fetch_version = "N/A"
        self.image_time_to_refresh = "N/A"

        try:
            with open(f"{self.config_dir}/image_cache.json") as f:
                data = json.load(f)

                self.image_fetch_date = datetime.strptime(
                    data["time"], "%Y-%m-%d %H:%M:%S.%f"
                )
                self.image_fetch_version = data["version"]
                self.image_time_to_refresh = timedelta(days=7) - (
                    datetime.now() - self.image_fetch_date
                )
        except Exception:
            pass

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
        """Checks if default images are present"""

        if not isdir(f"{self.image_dir}/default"):
            return False

        return True

    def is_outdated(self):
        """Checks if default images are outdated"""

        if not isfile(f"{self.config_dir}/image_cache.json"):
            return True

        try:
            with open(f"{self.config_dir}/image_cache.json") as f:
                data = json.load(f)

                if (
                    datetime.now()
                    - datetime.strptime(data["time"], "%Y-%m-%d %H:%M:%S.%f")
                ) > timedelta(days=7):
                    return True

                if data["version"] != version:
                    return True

                return False
        except Exception:
            return True

    def _verify(self, image: dict, file: str):
        def _exception(key):
            raise ParseError(f"image {file} is missing key {str(key)}")

        for key in (
            "meta",
            "uid",
            "name",
            "author",
            "docker_image",
            "command",
            "default_port",
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
