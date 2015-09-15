# -*- coding: utf-8 -*-
'''
RockBlock Interface Module
https://github.com/cuspaceflight/rockblock_ui

A module to make interfacing with a rockblock module more sane.
'''


class RockBlock(object):
    '''
    An interface to a RockBlock device.
    '''

    def __init__(self, serial_port):
        super(RockBlock, self).__init__()

    def send_recv(self, msg):
        '''
        Send a message to the device, return any messages received during the
        sending process.
        '''
        pass

    def recv_all(self):
        '''
        Receive all messages waiting, return them as a list.
        '''
        pass

    def msg_waiting(self):
        '''
        Return True if there are messages waiting to be received.
        '''
        pass

    def close(self):
        '''
        Shutdown the serial connection.
        '''
        pass
