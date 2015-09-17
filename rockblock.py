# -*- coding: utf-8 -*-
'''
RockBlock Interface Module
https://github.com/cuspaceflight/rockblock_ui

A module to make interfacing with a rockblock module more sane.
'''
import argparse
import collections
import datetime
import logging
import os
import time

import serial

# General command response codes
RSP_OK = "0"

# Status returned by +SBDSX Re: Iridium Command Ref Section 5.152
SBDSXStatus = collections.namedtuple("SBDSXStatus", ["mo", "momsn",
                                                     "mt", "mtmsn",
                                                     "ra", "msg_waiting"])
# Status returned by +SBDIX Re: Iridium Command Ref Section 5.144
SBDIXStatus = collections.namedtuple("SBDIXStatus", ["mo", "momsn",
                                                     "mt", "mtmsn",
                                                     "mt_len", "mt_queued"])


def utc_timestamp():
    return datetime.utcnow().isoformat()


def parse_comma_list(txt):
    '''
    Parse a string of form ' a, b, c' into a list [a, b, c]
    '''
    return [int(elm.strip()) for elm in txt.split(",")]


class RockBlock(object):
    '''
    An interface to a RockBlock device.
    '''

    def _log_msg(self, data):
        logging.info(data)
        if self.msg_log is not None:
            log_msg = "{ts} {data}\n".format(ts=utc_timestamp(),
                                             data=data)
            self.msg_log.write(log_msg.encode("ascii"))
            os.fdatasync(self.msg_log.fileno())

    def _write(self, data):
        return self.port.write(data.encode("ascii"))

    def _read_line(self):
        return self.port.readline().decode("ascii")

    def _send_command(self, command):
        '''
        Send command to the device after wrapping it in AT syntax.
        '''
        command = "AT" + command + "\r"
        logging.debug("Issuing command %s", command.encode("unicode_escape"))
        self._write(command)

    def _read_response(self):
        rsp = self._read_line().strip()
        logging.debug("Received response %s", rsp.encode("unicode_escape"))
        return rsp

    def _expect_response(self, value):
        '''
        Query the device for a response and evaluate that it matches the
        expected return.
        '''
        rsp = self._read_response()
        if rsp != value:
            logging.error("Expected response %s, got %s instead",
                          value.encode("unicode_escape"),
                          rsp.encode("unicode_escape"))
            raise Exception()  # TODO: Proper exceptions

    def _setup_device(self):
        # Check device verbose and echo settings
        self._send_command("")  # Empty AT command
        rsp = self._read_response()
        if rsp == "0":
            echo = False
            verbose = False
        elif rsp == "AT\r0":
            echo = True
            verbose = False
        elif rsp == "AT":
            echo = True
            verbose = True
        elif rsp == "":
            echo = False
            verbose = True

        if echo:
            self._send_command("E0")  # Disable command echos
            if verbose:
                self._expect_response("ATE0")  # Last of those
                self._expect_response("OK")
            else:
                self._expect_response("ATE0\r0")  # Last of those

        if verbose:
            self._send_command("V0")  # Disable verbose responses
            self._expect_response(RSP_OK)

        self._send_command("+SBDMTA=0")  # Disable ring alerts
        self._expect_response(RSP_OK)

    def __init__(self, serial_port, log_file=None):
        super(RockBlock, self).__init__()
        self.port = serial.Serial(serial_port, 19200, timeout=5)

        if log_file is not None:
            self.msg_log = open(log_file, "ab", buffering=0)
        else:
            self.msg_log = None

        self._setup_device()

    def check_sig_strength(self):
        self._send_command("+CSQF")
        rsp = self._read_response()
        if rsp[:6] == "+CSQF:":
            strength = int(rsp[6])
            self._expect_response(RSP_OK)
            return strength
        else:
            return -1

    def _write_msg_to_buffer(self, msg):
        self._send_command("+SBDWT")
        self._expect_response("READY")
        self._write(msg)
        self._write("\r")
        self._expect_response(RSP_OK)
        self._expect_response(RSP_OK)  # Not sure why I get two oks here

    def _check_msstm(self):
        self._send_command("-MSSTM")
        rsp = self._read_response()
        self._expect_response(RSP_OK)
        if rsp[:7] == "-MSSTM:":
            return rsp[8:] != "no network service"
        else:
            raise Exception()  # TODO: Proper exceptions

    def _msstm_ok(self):
        TIME_RETRIES = 20
        TIME_DELAY = 1
        for _ in range(TIME_RETRIES):
            if self._check_msstm():
                break
            time.sleep(TIME_DELAY)
        else:
            logging.error("Timed out due to invalid MSSTM")
            raise Exception()  # TODO: Proper exceptions

    def _signal_ok(self):
        SIGNAL_RETRIES = 3
        SIGNAL_DELAY = 10
        for _ in range(SIGNAL_RETRIES):
            if self.check_sig_strength() >= 2:
                break
            time.sleep(SIGNAL_DELAY)
        else:
            logging.error("Timed out due to insufficient signal strength")
            raise Exception()  # TODO: Proper exceptions

    def _session(self, a=False):
        if a:
            self._send_command("+SBDIXA")
        else:
            self._send_command("+SBDIX")
        rsp = self._read_response()
        while rsp == "":
            rsp = self._read_response()
        self._expect_response(RSP_OK)
        if rsp[:7] == "+SBDIX:":
            status = parse_comma_list(rsp[7:])
        elif rsp[:8] == "+SBDIXA:":
            status = parse_comma_list(rsp[8:])
        else:
            logging.error("Session request failed")
            raise Exception()  # TODO: Proper exceptions
        return SBDIXStatus(*status)

    def _send_buffer(self):
        incidental_recv = []
        SESSION_RETRIES = 3
        SESSION_DELAY = 1
        for _ in range(SESSION_RETRIES):
            status = self._session()
            if status.mt == 1:
                incidental_recv.append(
                    self._read_msg_from_buffer(status.mt_len))
            if status.mo <= 4:
                break
            time.sleep(SESSION_DELAY)
        else:
            logging.error("Timed out due to failed session")
            raise Exception()  # TODO: Proper exceptions
        self._send_command("+SBDD0")
        self._expect_response(RSP_OK)
        self._expect_response(RSP_OK)  # Another mystery double ok
        return incidental_recv

    def send_recv(self, msg):
        '''
        Send a message to the device, return any messages received during the
        sending process.
        '''
        if len(msg) > 360:
            logging.error("Message too long, maximum send size is 360 bytes")
            raise Exception()  # TODO: Proper exceptions
        self._write_msg_to_buffer(msg)
        self._msstm_ok()
        self._signal_ok()
        incidental = self._send_buffer()
        self._log_msg("---> " + msg)
        return incidental

    def _read_msg_from_buffer(self, mt_len):
        self._send_command("+SBDRT")
        rsp = self._read_response()
        if rsp[:7] == "+SBDRT:":
            cont = self._read_response()
            if len(cont) == (mt_len + 1) and cont[-1:] == "0":
                msg = cont[:-1]
                self._log_msg("<--- " + msg)
                return msg
            else:
                logging.error("Incorrect content length, expected %d, got %d\n"
                              "content: %s",
                              mt_len,
                              len(cont),
                              cont.encode("unicode_escape"))
                raise Exception()  # TODO: Proper exceptions
        else:
            logging.error("Failed to receive message correctly")
            raise Exception()  # TODO: Proper exceptions

    def recv_all(self):
        '''
        Receive all messages waiting, return them as a list.
        '''
        status = self._check_status()
        recv = []
        while self.msg_waiting(status):
            self._msstm_ok()
            self._signal_ok()
            sesh_status = self._session(a=status.ra)
            if sesh_status.mt == 1:
                recv.append(self._read_msg_from_buffer(sesh_status.mt_len))
            else:
                logging.error("Failed to receive message correctly")
                raise Exception()  # TODO: Proper exceptions
            status = self._check_status()
        return recv

    def _check_status(self):
        self._send_command("+SBDSX")
        rsp = self._read_response()
        if rsp[:7] == "+SBDSX:":
            self._expect_response(RSP_OK)
            status = parse_comma_list(rsp[7:])
            return SBDSXStatus(*status)
        else:
            raise Exception()  # TODO: Proper exceptions

    def msg_waiting(self, status=None):
        '''
        Return True if there are messages waiting to be received.
        '''
        if status is None:
            status = self._check_status()
        return status.ra == 1 or status.msg_waiting > 0

    def close(self):
        '''
        Shutdown the serial connection.
        '''
        self.port.close()
        if self.msg_log is not None:
            self.msg_log.close()


def recv_loop(rb):
    while recv_loop.run:
        rb.recv_all()
        time.sleep(10)
recv_loop.run = True


def main():
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="RockBLOCK interface module")
    parser.add_argument("--debug", action="store_true")
    sub = parser.add_subparsers()
    sub.required = True  # Bug http://bugs.python.org/issue9253#msg186387
    sub.dest = "cmd"
    sub.add_parser("recv")
    send = sub.add_parser("send")
    send.add_argument("msg")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if "RBUI_PORT" not in os.environ:
        print("Please set the RBUI_PORT env variable to the location of the "
              "rockblock serial port.")
        return
    if "RBUI_LOG" not in os.environ:
        print("Please set the RBUI_LOG env variable to the location of the "
              "message log file.")
        return

    rb = RockBlock(os.environ["RBUI_PORT"], os.environ["RBUI_LOG"])
    if args.cmd == 'send':
        rb.send_recv(args.msg)
    elif args.cmd == 'recv':
        recv_loop(rb)
    rb.close()


if __name__ == "__main__":
    main()
