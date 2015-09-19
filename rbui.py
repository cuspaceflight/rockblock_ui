#! /usr/bin/env python3
# -*- coding: utf-8 -*-
'''
RockBlock UI
https://github.com/cuspaceflight/rockblock_ui

Extremly basic command line interface to the rockblock module.
'''
import argparse
import logging
import logging.config
import os
import signal
import time

import rockblock


def _stop_recv(signum, frame):
    recv_loop.run = False


def recv_loop(rb):
    signal.signal(signal.SIGINT, _stop_recv)
    while recv_loop.run:
        logging.info("Checking for messages")
        try:
            rb.recv_all()
        except rockblock.RBTimeoutError:
            pass
        logging.info("Sleeping")
        time.sleep(10)
recv_loop.run = True


def main():
    try:
        port = os.environ['RBUI_PORT']
    except KeyError:
        port = "/dev/ttyUSB0"

    try:
        log_debug = os.environ['RBUI_LOG_DEBUG']
    except KeyError:
        log_debug = os.path.expanduser("~/rockblock_debug.log")

    try:
        log_msg = os.environ['RBUI_LOG_MSG']
    except KeyError:
        log_msg = os.path.expanduser("~/rockblock_messages.log")

    parser = argparse.ArgumentParser(description="RockBLOCK interface module")
    parser.add_argument("--debug", action="store_true")
    sub = parser.add_subparsers()
    sub.required = True  # Bug http://bugs.python.org/issue9253#msg186387
    sub.dest = "cmd"
    sub.add_parser("recv")
    send = sub.add_parser("send")
    send.add_argument("msg")

    args = parser.parse_args()

    logging.Formatter.converter = time.gmtime
    logging.config.dictConfig({
        "version": 1,
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "brief",
                "level": logging.DEBUG if args.debug else logging.INFO},
            "file": {
                "class": "logging.FileHandler",
                "formatter": "full",
                "level": logging.DEBUG,
                "filename": log_debug}},
        "formatters": {
            "brief": {"format": "%(asctime)s %(levelname)s: %(message)s",
                      "datefmt": "%Y-%m-%d %H:%M:%S"},
            "full": {"format": "%(asctime)s %(levelname)s L%(lineno)d: "
                               "%(message)s"}},
        "root": {
            "level": logging.DEBUG,
            "handlers": ["console", "file"]}
        })

    rb = rockblock.RockBlock(port, log_msg)
    if args.cmd == 'send':
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        rb.send_recv(args.msg)
    elif args.cmd == 'recv':
        recv_loop(rb)
    rb.close()


if __name__ == "__main__":
    main()
