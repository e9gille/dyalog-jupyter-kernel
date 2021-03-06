import json
import os
#import signal
import socket
import sys
import time
import subprocess
import codecs
                
from collections import deque


from pathlib import Path
from ipykernel.kernelbase import Kernel
from dyalog_kernel import __version__
from notebook.services.config import ConfigManager
from os.path import isfile, join
from bs4 import BeautifulSoup

if sys.platform.lower().startswith('win'):
    from winreg import *

handShake1 = b'\x00\x00\x00\x1cRIDESupportedProtocols=2'
handShake2 = b'\x00\x00\x00\x17RIDEUsingProtocol=2'

BUFFER_SIZE = 1024
DYALOG_HOST = '127.0.0.1'
DYALOG_PORT = 4502
TCP_TIMEOUT = 0.1

#_increment for port. To find first available
_port = DYALOG_PORT

#no of sec waiting for initial RIDE handshake. Slower systems should be greater no. of sec, to give dyalog a chance to start
RIDE_INIT_CONNECT_TIME_OUT = 3  #seconds


dq = deque()


def writeln(s):
    tmp_stdout = sys.stdout
    sys.stdout = sys.__stdout__
    print(s)
    sys.stdout = tmp_stdout




class DyalogKernel(Kernel):

    implementation = 'Dyalog'
    implementation_version = __version__
    language = 'APL'
    language_version = '0.1'


    language_info = {
        'name': 'APL',
        'mimetype': 'text/apl',
        'file_extension': '.apl'
    }




    banner = "Dyalog APL kernel"
    dyalogTCP = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    dyalogTCP.settimeout(TCP_TIMEOUT)
    connected = False


    # To save receive requests and prevent unneeded, lets put the max number here
    
    RIDE_PW = 32767


    dyalog_subprocess = None

    #def signal_handler(sig, frame):
    #     self.ride_send(["StrongInterrupt",{}])
    
    def out_error(self, s):
        _content = {
            'output_type': 'stream',
            'name': 'stderr',  # stdin or stderr
            'text': s
        }
        self.send_response(self.iopub_socket, 'stream', _content)

    def out_png(self, s):
        _content = {
            'output_type' : 'display_data',
            'data': {
                #'text/plain' : ['multiline text data'],
                'image/png':s,
                #'application/json':{
                   #JSON data is included as-is
                #  'json':'data',
                #},
            },
            'metadata' : {
                'image/svg':{
                    'width':120,
                    'height':80,
                },
            },
        }
        self.send_response(self.iopub_socket, 'display_data', _content)


    def out_html(self, s):
        _content = {
            # 'output_type': 'display_data',
            'data': {'text/html': s},
            'execution_count': self.execution_count,
            'metadata': ''
            # 'transient': ''
        }
        self.send_response(self.iopub_socket, 'execute_result', _content)


    def out_result(self, s):
        #injecting css: white-space:pre. Means no wrapping, RIDE SetPW will take care about line wrapping

        html_start = '<span style="white-space:pre; font-family: monospace">'
        html_end = '</span>'

        _content = {
            # 'output_type': 'display_data',
            # 'data': {'text/plain': s},
            'data': {'text/html': html_start + s + html_end},
            'execution_count': self.execution_count,
            'metadata': ''

            # 'transient': ''
        }

        self.send_response(self.iopub_socket, 'execute_result', _content)


    def out_stream(self, s):
        _content = {
            'output_type': 'stream',
            'name': 'stdin',  # stdin or stderr
            'text': s
        }
        self.send_response(self.iopub_socket, 'stream', _content)

    def dyalog_ride_connect(self):

        timeout = time.time() + RIDE_INIT_CONNECT_TIME_OUT




        while True:
            try:
                self.dyalogTCP.connect((DYALOG_HOST, self._port))
                break
            except socket.error as msg:
                #writeln(msg)
                if time.time()>timeout:
                    break


        #fcntl.fcntl(self.dyalogTCP, fcntl.F_SETFL, os.O_NONBLOCK)

        received = ['','']

        while self.ride_receive():
            pass

        if len(dq)>0:
            received = dq.pop()

        if received[0] == handShake1[8:].decode("utf-8"):
            # handshake1
            self.dyalogTCP.send(handShake1)
            writeln("SEND " + handShake1[8:].decode("utf-8"))
            # handshake2
            while self.ride_receive():
                pass
            if len(dq) > 0:
                received = dq.pop()
            if received[0] == handShake2[8:].decode("utf-8"):
                # handshake2
                self.dyalogTCP.send(handShake2)
                writeln("SEND " + handShake2[8:].decode("utf-8"))

                d = ["Identify", {"identity": 1}]
                self.ride_send(d)

                d = ["Connect", {"remoteId": 2}]
                self.ride_send(d)

                d = ["GetWindowLayout", {}]
                self.ride_send(d)

                while self.ride_receive():
                    pass
                if len(dq) > 0:
                    received = dq.pop()

                d = ["SetPW", {"pw": self.RIDE_PW}]
                self.ride_send(d)
                while self.ride_receive():
                    pass
                self.connected = True
                #signal.signal(signal.SIGABRT, self.signal_handler) #activate interrupt handler
                #signal.signal(signal.SIGFPE, self.signal_handler) #activate interrupt handler
                #signal.signal(signal.SIGILL, self.signal_handler) #activate interrupt handler
                #signal.signal(signal.SIGINT, self.signal_handler) #activate interrupt handler
                #signal.signal(signal.SIGSEGV, self.signal_handler) #activate interrupt handler
                #signal.signal(signal.SIGTERM, self.signal_handler) #activate interrupt handler
                #signal.signal(signal.SIGBREAK, self.signal_handler) #activate interrupt handler


    def __init__(self, **kwargs):





        # path to connection_file. In case we need it in the close future
        #from ipykernel import get_connection_file
        #s = get_connection_file()
        #writeln("########## " + str(s))




        self._port = DYALOG_PORT
        # lets find first available port, starting from default DYALOG_PORT (:4502)
        # this makes sense only if Dyalog APL and Jupyter executables are on the same host (localhost)
        if DYALOG_HOST == '127.0.0.1':
            
            while True:
                sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
                result = sock.connect_ex((str(DYALOG_HOST).strip(),self._port))
                sock.close()
                #port is available
                if result !=0:
                    break
                else:
                    #try next port
                    self._port += 1




        # if Dyalog APL and Jupyter executables are on the same host (localhost) let's start instance of Dyalog
        if DYALOG_HOST == '127.0.0.1':
            if sys.platform.lower().startswith('win'):
                #Windows. Let's find an installed version to use
                hklmReg = ConnectRegistry(None,HKEY_LOCAL_MACHINE)
                dyalogKey = OpenKey(hklmReg, r"SOFTWARE\Dyalog")
                installCount = QueryInfoKey(dyalogKey)[0]
                for n in range(installCount):
                    currInstall = EnumKey(dyalogKey, installCount - (n + 1))
                    if currInstall[:12] == "Dyalog APL/W":
                        break
                lastKey = OpenKey(hklmReg, r"SOFTWARE\\Dyalog\\" + currInstall)
                dyalogPath = QueryValueEx(lastKey,"dyalog")[0] + "\\dyalog.exe"
                CloseKey(dyalogKey)
                CloseKey(lastKey)
                self.dyalog_subprocess = subprocess.Popen([dyalogPath,"RIDE_SPAWNED=1",'RIDE_INIT=SERVE::' + str(self._port).strip(),  os.path.dirname(os.path.abspath(__file__)) + '/init.dws'])
            else:
                #linux, darwin... etc
                dyalog_env = os.environ.copy()
                dyalog_env['RIDE_INIT'] = 'SERVE::' + str(self._port).strip()
                #start dyalog executable in xterm. Req: xterm must be installed. dyalog should be in the path
                #self.dyalog_subprocess  = subprocess.Popen(['xterm', '-e', ('dyalog ' + os.path.dirname(os.path.abspath(__file__)) + '/init.dws')], env=dyalog_env)
                self.dyalog_subprocess = subprocess.Popen(['dyalog', '+s', '-q', os.path.dirname(os.path.abspath(__file__)) + '/init.dws'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dyalog_env)




        #disable auto closing of brackets/quotation marks. Not very useful in APL
        #Pass None instead of False to restore auto-closing feature
        c = ConfigManager()
        c.update('notebook', {'CodeCell': {'cm_config': {'autoCloseBrackets': False}}})

        Kernel.__init__(self, **kwargs)




        self.dyalog_ride_connect()


    # return False if no RIDE message has been received
    def ride_receive(self):

        data = b''

        rcv = False;

        while True:

            try:
                received = self.dyalogTCP.recv(BUFFER_SIZE)
            except socket.timeout:
                received = b''
                writeln('no data')


            data = data + received
            if len(received)==0:
                break

        #lets parse one or more received RIDE messages
        c_pos=0

        while True:
            #no RIDE message can be less then 8 bytes in length
            if len(data)>8:
        
                if sys.version_info[0]<3:
                    ch1 = data[c_pos + 4].decode("utf-8")
                    ch2 = data[c_pos + 5].decode("utf-8")
                    ch3 = data[c_pos + 6].decode("utf-8")
                    ch4 = data[c_pos + 7].decode("utf-8")
                    ride_id = ch1+ch2+ch3+ch4
                else:
                    ride_id = chr(data[c_pos+4]) + chr(data[c_pos+5]) + chr(data[c_pos+6]) + chr(data[c_pos+7])
                
                
                
                if sys.version_info[0]<3:
                    msg_size = ord(data[c_pos])*0x1000000+ord(data[c_pos+1])*0x10000+ord(data[c_pos+2])*0x100+ord(data[c_pos+3])
                else:
                    msg_size = data[c_pos]*0x1000000+data[c_pos+1]*0x10000+data[c_pos+2]*0x100+data[c_pos+3]

                rideMessage = data[c_pos+8:c_pos+msg_size]
                if ride_id=="RIDE":
                    if rideMessage[:14] == b'["ReplyGetLog"':
                        rideMessage = b'["ReplyGetLog",{"result":[]}]' # notebooks don't need a session log
                    try:
                        rideMessage = rideMessage.decode("utf-8")
                    except: 
                        writeln("JSON parser error")
                        return False

                    # json, fix all \r and \n. They should be escaped appropriately for JSON
                    rideMessage = rideMessage.replace('\n', '\\n')
                    rideMessage = rideMessage.replace('\r', '\\r')


                    rcv = True

                    try:
                        json_data = json.loads(rideMessage)
                    except:
                        #what's been received is not RIDEs standard JSON, it has to be one of the 2 first string type handshake messages
                        json_data = []
                        json_data.append(rideMessage)
                        json_data.append("String")

                    writeln("RECV " + rideMessage)
                    dq.appendleft(json_data)


                else:
                    writeln('ERROR: not a RIDE message!')

                c_pos = c_pos + msg_size

            else:
               if len(data)>0:
                    writeln('Not a RIDE message, too short')
               data = b''

            if c_pos>=len(data):
               break
        return rcv

    # d is python  list, json.
    def ride_send(self, d):
        json_str = 'XXXXRIDE' + json.dumps(d)

        # json, fix all \r and \n. They should be escaped appropriately for JSON
        json_str.replace('\n', '\\n')
        json_str.replace('\r', '\\r')

        _data = bytearray(str.encode(json_str))

        l = len(_data)

        _data[0] = (l >> 24) & 0xff
        _data[1] = (l >> 16) & 0xff
        _data[2] = (l >> 8) & 0xff
        _data[3] = l & 0xff

        self.dyalogTCP.send(_data)
        writeln("SEND " + _data[8:].decode("utf-8"))



    # No need for autocomplete functionality <TAB>
    #
    #
    '''
    def do_complete(self, code, cursor_pos):




        try:
            resp = self.apl_keymap[code[cursor_pos-1]]
            return {'matches': [resp],
                    'cursor_start': cursor_pos - 1,
                    'cursor_end': cursor_pos,
                    'metadata': [],
                    'status': 'ok'

                    }
        except:

            return {'matches': '',
                    'cursor_start': cursor_pos,
                    'cursor_end': cursor_pos,
                    'metadata': [],
                    'status': 'ok'

                    }



    '''


    def do_execute(self, code, silent, store_history=True, user_expressions=None,
                   allow_stdin=True):
        code = code.strip()

        if not silent:
            if self.connected:
                code = code + '\n'
                d = ["Execute", {"trace": 0, "text": code}]
                self.ride_send(d)

                PROMPT_AVAILABLE = True
                err = False
                data_collection =''

                self.ride_receive()

                # as long as we have queue dq or RIDE PROMPT is not available... do loop
                while (len(dq)>0 or not PROMPT_AVAILABLE):

                    received = ['','']
                    # in case prompt is not available e.g time consuming calculations, make sure dq is not empty.
                    if len(dq) > 0:
                        received = dq.pop()

                    if received[0]=='AppendSessionOutput':
                        if not PROMPT_AVAILABLE:
                            data_collection = data_collection + received[1].get('result')
                    elif received[0]=='SetPromptType':
                        if received[1].get('type') == 0:
                            PROMPT_AVAILABLE = False
                        else:
                            PROMPT_AVAILABLE = True
                            if len(data_collection) > 0:
                                if err:
                                    self.out_error(data_collection)
                                else:
                                    self.out_result(data_collection)
                                data_collection = ''
                            err = False
                    elif received[0]=='ShowHTML':
                        self.out_html(received[1].get('html'))
                    elif received[0]=='HadError':
                        # in case of error, set the flag err
                        # it should be reset back to False only when prompt is available again.
                        err = True
                    #actually we don't want echo
                    elif received[0]=='EchoInput':
                        pass
                    if len(dq)==0:
                        self.ride_receive()
                    #self.pa(received[1].get('input'))

            else:
                self.out_error('Dyalog APL not connected')

        reply_content = {'status': 'ok',
                # The base class increments the execution count
                'execution_count': self.execution_count,
                'payload': [],
                'user_expressions': {},
                }





        return reply_content




    def do_shutdown(self, restart):
        #shutdown Dyalog executable only if Jupyter kernel has started it.

        if DYALOG_HOST == '127.0.0.1':
            if self.connected:
                self.ride_send(["Exit", {"code": 0}])
         #   time.sleep(2)
         #   if self.dyalog_subprocess:
         #       self.dyalog_subprocess.kill()

        self.dyalogTCP.close()
        self.connected = False
        return {'status': 'ok', 'restart': restart}
