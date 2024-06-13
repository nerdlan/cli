#################################################################
#                                                               #
# Wilfred                                                       #
# Copyright (C) 2020-2022, Vilhelm Prytz, <vilhelm@prytznet.se> #
#                                                               #
# Licensed under the terms of the MIT license, see LICENSE.     #
# https://github.com/wilfred-dev/wilfred                        #
#                                                               #
#################################################################

import sqlite3
import click

from appdirs import user_data_dir
from os.path import isfile
from os import remove

from wilfred.message_handler import error
from wilfred.api.database import session, Server, EnvironmentVariable


class Migrate:
    def __init__(self):
        self._legacy_sqlite_path = f"{user_data_dir()}/wilfred/wilfred.db"

        # perform checks
        self._legacy_sqlite_db_check()

    def _legacy_sqlite_query(self, query):
        result = []

        try:
            conn = sqlite3.connect(self._legacy_sqlite_path)
            conn.row_factory = sqlite3.Row

            cur = conn.cursor()
            cur.execute(query)

            for r in cur.fetchall():
                result.append(dict(r))

            conn.commit()
            conn.close()
        except sqlite3.OperationalError as e:
            error(
                "could not communicate with database " + click.style(str(e), bold=True),
                exit_code=1,
            )
        except sqlite3.IntegrityError as e:
            error("invalid input " + click.style(str(e), bold=True), exit_code=1)

        return result

    def _legacy_sqlite_db_check(self):
        if isfile(self._legacy_sqlite_path):
            for server in self._legacy_sqlite_query("SELECT * FROM servers"):
                session.add(
                    Server(
                        id=server["id"],
                        name=server["name"],
                        image_uid=server["image_uid"],
                        memory=server["memory"],
                        port=server["port"],
                        custom_startup=server["custom_startup"],
                        status=server["status"],
                    )
                )

            try:
                session.commit()
            except Exception as e:
                error(str(e), exit_code=1)

            for variable in self._legacy_sqlite_query("SELECT * FROM variables"):
                session.add(
                    EnvironmentVariable(
                        server_id=variable["server_id"],
                        variable=variable["variable"],
                        value=variable["value"],
                    )
                )

            try:
                session.commit()
            except Exception as e:
                error(str(e), exit_code=1)

            try:
                remove(f"{self._legacy_sqlite_path}")
            except Exception as e:
                error(str(e), exit_code=1)
