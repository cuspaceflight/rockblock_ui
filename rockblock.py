# -*- coding: utf-8 -*-
'''
RockBlock Interface Module
https://github.com/cuspaceflight/rockblock_ui

A module to make interfacing with a rockblock module more sane.
'''
import collections
import datetime
import logging
import os
import time

import serial

# General command response codes
RSP_OK = "0"

# Buffer IDs
MO_BUF = "0"
MT_BUF = "1"
ALL_BUF = "2"

# Status returned by +SBDSX Re: Iridium Command Ref Section 5.152
SBDSXStatus = collections.namedtuple("SBDSXStatus", ["mo", "momsn",
                                                     "mt", "mtmsn",
                                                     "ra", "msg_waiting"])
# Status returned by +SBDIX Re: Iridium Command Ref Section 5.144
SBDIXStatus = collections.namedtuple("SBDIXStatus", ["mo", "momsn",
                                                     "mt", "mtmsn",
                                                     "mt_len", "mt_queued"])


class RockBlockException(Exception):
    def __init__(self, *args, **kwargs):
        super(RockBlockException, self).__init__(*args, **kwargs)


class RBTimeoutError(RockBlockException):
    def __init__(self, query, num):
        super(RBTimeoutError, self).__init__()
        self.query = query
        self.num = num

    def __str__(self):
        return "{} timed out after {:d} attempts".format(self.query, self.num)


class DeviceError(RockBlockException):
    def __init__(self, error, rsp):
        super(DeviceError, self).__init__(error,
                                          rsp.encode("unicode_escape"))


class ExpectationFailure(RockBlockException):
    def __init__(self, expected, actual):
        super(ExpectationFailure, self).__init__()
        self.expected = expected
        self.actual = actual

    def __str__(self):
        return "Unexpected response, expected {}, received {}".format(
            self.expected.encode("unicode_escape"),
            self.actual.encode("unicode_escape"))


class MessageTooLongError(RockBlockException):
    def __init__(self, *args, **kwargs):
        super(MessageTooLongError, self).__init__(*args, **kwargs)


class IncorrectContentLengthError(RockBlockException):
    def __init__(self, length, cont):
        super(IncorrectContentLengthError, self).__init__()
        self.length = length
        self.cont = cont

    def __str__(self):
        return("Unexpected content length, expected {:d}, got {:d}\n"
               "Content: {}".format(self.length,
                                    len(self.cont),
                                    self.cont.encode("unicode_escape")))


def utc_timestamp():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat()


def parse_comma_list(txt):
    '''
    Parse a string of form ' a, b, c' into a list [a, b, c]
    '''
    return [int(elm.strip()) for elm in txt.split(",")]


class ATModem(object):
    def __init__(self, serial_port):
        self.port = serial.Serial(serial_port, 19200, timeout=5)

    def _raw_write(self, msg):
        return self.port.write(msg.encode("ascii"))

    def _raw_read(self):
        return self.port.readline().decode("ascii")

    def command(self, cmd):
        command = "AT" + cmd + "\r"
        logging.debug("Issuing command %s", command.encode("unicode_escape"))
        self._raw_write(command)

    def response(self, expect=None, retry=0):
        '''
        If expect is not None then it will throw an exception
        if the response does not match except.
        If retry is non-zero, it will retry the read until the value
        is not '', upto retry times.
        If both are given it will retry and if it gets a valid result
        it will check it against except.
        '''
        rsp = self._raw_read()

        for i in range(retry):
            if rsp != "":
                break
            rsp = self._raw_read()

        if rsp == "":
            raise RBTimeoutError("Read", retry)

        rsp = rsp.strip()

        logging.debug("Received response %s", rsp.encode("unicode_escape"))

        if expect is not None and rsp != expect:
            raise ExpectationFailure(expect, rsp)
        return rsp

    def close(self):
        self.port.close()


class RockBlock(object):
    '''
    An interface to a RockBlock device.
    '''

    def _log_msg(self, data):
        logging.info(data)
        if self.msg_log is not None:
            log_msg = "{ts} {data}\n".format(ts=utc_timestamp(), data=data)
            self.msg_log.write(log_msg.encode("ascii"))
            os.fdatasync(self.msg_log.fileno())

    def _setup_device(self):
        # Check device verbose and echo settings
        self.mod.command("")  # Empty AT command
        rsp = self.mod.response()
        if rsp == "0":
            echo = False
            verbose = False
        elif rsp == "AT\r0":
            echo = True
            verbose = False
        elif rsp == "AT" or rsp == "":
            rspp = self.mod.response()
            if rspp == "OK":
                echo = True
                verbose = True
            else:
                echo = False
                verbose = True

        if echo:
            self.mod.command("E0")  # Disable command echos
            if verbose:
                self.mod.response(expect="ATE0")  # Last of those
                self.mod.response(expect="OK")
            else:
                self.mod.response(expect="ATE0\r0")  # Last of those

        if verbose:
            self.mod.command("V0")  # Disable verbose responses
            self.mod.response(expect=RSP_OK)

        self.mod.command("+SBDMTA=0")  # Disable ring alerts
        self.mod.response(expect=RSP_OK)

    def _reset_device(self):
        self.mod.command("E1V1")  # Revert to echo and verbose modes
        self.mod.response(expect="")
        self.mod.response(expect="OK")

    def __init__(self, serial_port, log_file=None):
        super(RockBlock, self).__init__()

        self.mod = ATModem(serial_port)

        if log_file is not None:
            self.msg_log = open(log_file, "ab", buffering=0)
        else:
            self.msg_log = None

        self._setup_device()

    def check_sig_strength(self):
        try:
            self.mod.command("+CSQF")
            rsp = self.mod.response()
            if rsp[:6] == "+CSQF:":
                strength = int(rsp[6])
                self.mod.response(expect=RSP_OK)
                return strength
            else:
                raise DeviceError("Error querying signal strength", rsp)
        except RockBlockException:
            logging.exception("")
            raise

    def _write_msg_to_buffer(self, msg):
        logging.info("Writing message to output buffer")
        self.mod.command("+SBDWT")
        self.mod.response(expect="READY")
        self.mod._raw_write(msg)
        self.mod._raw_write("\r")
        self.mod.response(expect=RSP_OK)
        self.mod.response(expect=RSP_OK)  # Not sure why I get two oks here
        logging.info("Message written")

    def _check_msstm(self):
        logging.info("Checking network time")
        self.mod.command("-MSSTM")
        rsp = self.mod.response()
        self.mod.response(expect=RSP_OK)
        if rsp[:7] == "-MSSTM:":
            return rsp[8:] != "no network service"
        else:
            raise DeviceError("Error querying network time", rsp)

    def _msstm_ok(self):
        TIME_RETRIES = 20
        TIME_DELAY = 1
        for i in range(TIME_RETRIES):
            if self._check_msstm():
                break
            logging.info("Network time FAIL")
            if i < TIME_RETRIES-1:
                time.sleep(TIME_DELAY)
        else:
            raise RBTimeoutError("Network time query", TIME_RETRIES)
        logging.info("Network time OK")

    def _signal_ok(self):
        logging.info("Checking signal availability")
        SIGNAL_RETRIES = 3
        SIGNAL_DELAY = 10
        for i in range(SIGNAL_RETRIES):
            sig = self.check_sig_strength()
            if sig >= 2:
                break
            logging.info("Signal %d/5 FAIL", sig)
            if i < SIGNAL_RETRIES-1:
                time.sleep(SIGNAL_DELAY)
        else:
            raise RBTimeoutError("Signal strength query", SIGNAL_RETRIES)
        logging.info("Signal %d/5 OK", sig)

    def _session(self, a=False):
        if a:
            self.mod.command("+SBDIXA")
        else:
            self.mod.command("+SBDIX")
        rsp = self.mod.response(retry=5)
        self.mod.response(expect=RSP_OK)
        if rsp[:7] == "+SBDIX:":
            status = SBDIXStatus(*parse_comma_list(rsp[7:]))
        elif rsp[:8] == "+SBDIXA:":
            status = SBDIXStatus(*parse_comma_list(rsp[8:]))
        else:
            raise DeviceError("Error initiating satellite session", rsp)
        logging.debug(status)
        return status

    def _clear_buffer(self, buf_id):
        self.mod.command("+SBDD{}".format(buf_id))
        self.mod.response(expect=RSP_OK)
        self.mod.response(expect=RSP_OK)  # Another mystery double ok

    def _send_buffer(self):
        logging.info("Establishing session with satellite")
        incidental_recv = []
        SESSION_RETRIES = 3
        SESSION_DELAY = 1

        # Check that there are no message left in the recv buffer
        if self._check_status().mt == 1:
            incidental_recv.append(self._read_msg_from_buffer())

        for _ in range(SESSION_RETRIES):
            status = self._session()
            if status.mt == 1:
                incidental_recv.append(
                    self._read_msg_from_buffer(status.mt_len))
            if status.mo <= 4:
                break
            time.sleep(SESSION_DELAY)
        else:
            raise RBTimeoutError("Buffer send", SESSION_RETRIES)
        self._clear_buffer(MO_BUF)
        return incidental_recv

    def _recv_buffer(self, a):
        logging.info("Establishing session with satellite")
        SESSION_RETRIES = 3
        SESSION_DELAY = 1
        for _ in range(SESSION_RETRIES):
            status = self._session(a)
            if status.mt == 1:
                break
            time.sleep(SESSION_DELAY)
        else:
            raise RBTimeoutError("Buffer recv", SESSION_RETRIES)
        recv = self._read_msg_from_buffer(status.mt_len)
        return recv

    def send_recv(self, msg):
        '''
        Send a message to the device, return any messages received during the
        sending process.
        '''
        try:
            if len(msg) > 360:
                raise MessageTooLongError("Maximum send size is 360 bytes")
            self._write_msg_to_buffer(msg)
            self._msstm_ok()
            self._signal_ok()
            incidental = self._send_buffer()
            self._log_msg("---> " + msg)
            return incidental
        except RockBlockException:
            logging.exception("")
            raise

    def _read_msg_from_buffer(self, mt_len=-1):
        logging.info("Reading message from buffer")
        self.mod.command("+SBDRT")
        rsp = self.mod.response()
        if rsp[:7] == "+SBDRT:":
            cont = self.mod.response()
            if cont[-1:] == "0" and (mt_len == -1 or
                                     len(cont) == (mt_len + 1)):
                msg = cont[:-1]
                self._log_msg("<--- " + msg)
                self._clear_buffer(MT_BUF)
                return msg
            else:
                raise IncorrectContentLengthError(mt_len, cont)
        else:
            raise DeviceError("Error reading message from device buffer", rsp)

    def recv_all(self):
        '''
        Receive all messages waiting, return them as a list.
        '''
        try:
            status = self._check_status()
            recv = []
            while self.msg_waiting(status):
                logging.info("Messages waiting to be received")
                if status.mt == 1:
                    recv.append(self._read_msg_from_buffer())
                else:
                    self._msstm_ok()
                    self._signal_ok()
                    recv.append(self._recv_buffer(a=status.ra))
                status = self._check_status()
            return recv
        except RockBlockException:
            logging.exception("")
            raise

    def _check_status(self):
        self.mod.command("+SBDSX")
        rsp = self.mod.response()
        if rsp[:7] == "+SBDSX:":
            self.mod.response(expect=RSP_OK)
            status = SBDSXStatus(*parse_comma_list(rsp[7:]))
            logging.debug(status)
            return status
        else:
            raise DeviceError("Error querying device status", rsp)

    def msg_waiting(self, status=None):
        '''
        Return True if there are messages waiting to be received.
        '''
        try:
            if status is None:
                status = self._check_status()
            return status.mt == 1 or status.ra == 1 or status.msg_waiting > 0
        except RockBlockException:
            logging.exception("")
            raise

    def close(self):
        '''
        Shutdown the serial connection.
        '''
        self._reset_device()
        self.mod.close()
        if self.msg_log is not None:
            self.msg_log.close()
