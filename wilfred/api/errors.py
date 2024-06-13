#################################################################
#                                                               #
# Wilfred                                                       #
# Copyright (C) 2020-2022, Vilhelm Prytz, <vilhelm@prytznet.se> #
#                                                               #
# Licensed under the terms of the MIT license, see LICENSE.     #
# https://github.com/wilfred-dev/wilfred                        #
#                                                               #
#################################################################


class WilfredException(Exception):
    """
    A base class from which all other exceptions inherit.

    If you want to catch all errors that the Wilfred API might raise,
    catch this base exception. Though, dependencies of Wilfred might
    raise other exceptions which this base exception does not cover.
    """


class ReadError(WilfredException):
    """
    Exception occured while reading file
    """


class ParseError(WilfredException):
    """
    Exception occured while parsing file (malformed or missing variables)
    """


class WriteError(WilfredException):
    """
    Exception occured while wiring to file (permission denied or invalid path)
    """
