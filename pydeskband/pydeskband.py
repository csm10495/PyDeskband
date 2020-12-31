import os
import pathlib
import sys
import time

from dataclasses import dataclass
from threading import Thread, Event
from typing import Union

@dataclass
class Size:
    ''' a Python-version of the SIZE struct in WinApi '''
    x: int
    y: int

class _LogTailer(Thread):
    ''' A Thread that can follow/print new lines in the pydeskband log file (which is written by the DLL) '''
    LOG_PATH = pathlib.Path(os.path.expandvars('%TEMP%/pydeskband.log'))
    def __init__(self):
        self.exit_event = Event()

        if not _LogTailer.LOG_PATH.is_file():
            raise FileNotFoundError("PyDeskband log was not found")

        self.starting_offset = _LogTailer.LOG_PATH.stat().st_size

        Thread.__init__(self, daemon=True)

    def run(self):
        ''' Ran in the other thread. Will effectively 'tail -f' the log file and print to stderr the new lines '''
        with open(_LogTailer.LOG_PATH, 'rb') as log_file:
            log_file.seek(self.starting_offset)
            while not self.exit_event.is_set():
                line = log_file.readline().rstrip().decode()
                if line:
                    print(line, file=sys.stderr)
                time.sleep(.01)

class ControlPipe:
    ''' The mechanism for controlling PyDeskband.'''
    def __init__(self):
        ''' Note that this may raise if PyDeskband is not in use '''
        try:
            self.pipe = open('\\\\.\\pipe\\PyDeskbandControlPipe', 'r+b', buffering=0)
        except FileNotFoundError as ex:
            raise FileNotFoundError(f"The PyDeskbandControlPipe is not available. Is the deskband enabled?.. {str(ex)}")
        self._log_tailer = None

    def __enter__(self):
        ''' For use as a contextmanager '''
        return self

    def __exit__(self, type, value, traceback):
        ''' For use as a contextmanager... Closes the handle to the pipe '''
        self.pipe.close()

    def send_command(self, cmd:Union[list, tuple, str], check_ok:bool=True) -> str:
        '''
        The main entry point to go from Python to/from the C++ code. It is very unlikely that a regular user
        would want to call this directly. If something is done incorrectly here, PyDeskband will likely crash...
            and that will lead to Windows Explorer restarting.

        Arguments:
            cmd: Either a list of command keywords or a string of a full command
            check_ok: If True, raise ValueError if C++ does not give back "OK"
                All commands that don't give back a specific response, return "OK"

        Returns:
            A string of the response given from PyDeskband
        '''
        if isinstance(cmd, (list, tuple)):
            cmd = ','.join([str(c) for c in cmd])

        cmd = cmd.encode()

        bytes_written = self.pipe.write(cmd)
        if bytes_written != len(cmd):
            raise RuntimeError(f"Unable to write all the bytes down the pipe. Wrote: {bytes_written} instead of {len(cmd)}")

        response = self.pipe.readline().strip().decode()

        if check_ok and response != 'OK':
            raise ValueError(f"Response was not OK. It was: {response}")

        return response

    def get_width(self) -> int:
        ''' Get the current width (in pixels) of the deskband '''
        return int(self.send_command(['GET', 'WIDTH'], check_ok=False))

    def get_height(self) -> int:
        ''' Get the current height (in pixels) of the deskband '''
        return int(self.send_command(['GET', 'HEIGHT'], check_ok=False))

    def get_text_info_count(self) -> int:
        ''' Get the count of TextInfos currently saved '''
        return int(self.send_command(['GET', 'TEXTINFOCOUNT'], check_ok=False))

    def add_new_text_info(self, text:str, x:int=0, y:int=0, red:int=255, green:int=255, blue:int=255) -> None:
        ''' Creates a new TextInfo with the given text,x/y, and rgb text color '''
        self.send_command('NEW_TEXTINFO')

        self.send_command([
            'SET', 'RGB', red, green, blue
        ])
        self.send_command([
            'SET', 'XY', x, y
        ])
        self.send_command([
            'SET', 'TEXT', self._verify_input_text(text)
        ])

    def modify_text_info(self, idx:int, text:str) -> None:
        ''' Sets the text of the TextInfo at the given index '''
        self.send_command(["SET", "TEXTINFO_TARGET", str(idx)])
        self.send_command([
            'SET', 'TEXT', self._verify_input_text(text)
        ])
        self.send_command(["SET", "TEXTINFO_TARGET"])

    def get_text_size(self, text:str) -> Size:
        ''' Gets a Size object corresponding with the x,y size this text would be (likely in pixels) '''
        x, y = self.send_command([
            'GET', 'TEXTSIZE', self._verify_input_text(text)
        ], check_ok=False).split(',')
        return Size(x, y)

    def paint(self) -> None:
        ''' Requests that PyDeskband repaint all TextInfos now '''
        self.send_command('PAINT')

    def clear(self) -> None:
        ''' Clears all TextInfos and re-paints '''
        self.send_command('CLEAR')

    def set_logging(self, enabled:bool, tail:bool=False) -> None:
        '''
        Enables/disables logging in the C++ module. Logging goes to %TEMP%/pydeskband.log.
        If tail is True, will attempt to tail the output to stderr in Python.
         '''
        self.send_command([
            'SET', 'LOGGING_ENABLED', 1 if enabled else 0
        ])

        def _stop_log_tailer():
            if self._log_tailer:
                self._log_tailer.exit_event.set()
                self._log_tailer.join()
                self._log_tailer = None

        if tail:
            _stop_log_tailer()
            self._log_tailer = _LogTailer()
            self._log_tailer.start()
        else:
            _stop_log_tailer()

    def _send_message(self, msg:int) -> None:
        ''' Likely only useful for debugging. Send a WM_... message with the given id to our hwnd.'''
        self.send_command([
            'SENDMESSAGE', str(msg)
        ])

    def _verify_input_text(self, text) -> str:
        ''' Helper function. Verifies that the delimiter is not in the given text. Returns the text if not found. Otherwise raises. '''
        if ',' in text:
            raise ValueError(f"text cannot contain a ',' sign. Text: {text}")
        return text

    def __test(self):
        ''' a test '''
        import psutil, time

        def get_bytes_recv():
            return psutil.net_io_counters().bytes_recv

        self.clear()

        cpu = 100 - psutil.cpu_times_percent(interval=1).idle
        # idx = 0
        self.add_new_text_info(f'CPU: {cpu}')

        # idx = 1
        self.add_new_text_info(f'IDown: XX', y=20)

        self.paint()

        lastBytes = get_bytes_recv()
        lastStamp = time.time()

        while True:
            cpu = 100 - psutil.cpu_times_percent(interval=1).idle
            self.modify_text_info(0, f'CPU: {cpu}')

            thisBytes = get_bytes_recv()

            mbps = int(float(thisBytes - lastBytes) / 125000.0 / (time.time() - lastStamp))
            lastStamp = time.time()

            self.modify_text_info(1, f'IDown: {mbps} Mbps')
            lastBytes = thisBytes

            self.paint()
