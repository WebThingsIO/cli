#!/usr/bin/env python3

'''This file contains the main program for the Mozilla IoT gateway
command line interface.
'''

import argparse
import json
import logging
import os
import pathlib
import sys

from cli.command_line import CommandLine
from cli.gateway import GatewayConfig
from cli.log_setup import log_setup


def main():
    '''The main program.'''
    parser = argparse.ArgumentParser(
        prog='cli',
        usage='%(prog)s [options] [command]',
        description='Send commands to a Mozilla IoT gateway',
    )
    parser.add_argument(
        '-f', '--file',
        dest='filename',
        help='Specifies a file of commands to process.'
    )
    parser.add_argument(
      '-g', '--gateway',
      dest='gateway',
      help='Specifies the URL of the gateway to connect to'
    )
    parser.add_argument(
        '-d', '--debug',
        dest='debug',
        action='store_true',
        help='Enable debug features',
        default=False
    )
    parser.add_argument(
        '-v', '--verbose',
        dest='verbose',
        action='store_true',
        help='Turn on verbose messages',
        default=False
    )
    parser.add_argument(
        'cmd',
        nargs='*',
        help='Optional command to execute'
    )
    args = parser.parse_args(sys.argv[1:])

    script_dir = os.path.dirname(os.path.realpath(__file__))

    log_setup()
    log = logging.getLogger()
    if args.debug:
        log.setLevel(logging.DEBUG)

    if args.verbose:
        log.info('debug = %s', args.debug)
        log.info('gateway = %s', args.gateway)
        log.info('cmd = [%s]', ', '.join(args.cmd))
        log.info('script_dir = %s', script_dir)

    config = GatewayConfig()

    cmd_line = CommandLine(config)
    cmd_line.auto_cmdloop(' '.join(args.cmd))

    config.save()

    #if args.filename:
    #    with open(args.filename) as cmd_file:
    #        cmd_line = CommandLine(bus, dev_types, stdin=cmd_file,
    #                               filename=args.filename)
    #        cmd_line.auto_cmdloop('')
    #else:
    #    cmd_line = CommandLine(bus, dev_types)
    #    cmd_line.auto_cmdloop(' '.join(args.cmd))

main()
