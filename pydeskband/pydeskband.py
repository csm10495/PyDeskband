import contextlib
import os
import pathlib
import sys
import time

from dataclasses import dataclass
from threading import Thread, Event
from typing import Union

@dataclass
class Size:
    ''' A Python-version of the SIZE struct in WinApi '''
    x: int
    y: int

@dataclass
class Color:
    ''' Representation of an RGB color '''
    red: int
    green: int
    blue: int

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
        self._set_color(red, green, blue)
        self._set_coordinates(x, y)
        self._set_text(text)
        idx = (self.get_text_info_count() - 1)
        return TextInfo(self, idx)

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

    def _set_text(self, text:str) -> str:
        ''' Call to SET TEXT in the DLL '''
        return self.send_command([
            'SET', 'TEXT', self._verify_input_text(text)
        ])

    def _set_color(self, red:int=255, green:int=255, blue:int=255) -> str:
        ''' Call to SET RGB in the DLL '''
        return self.send_command([
            'SET', 'RGB', red, green, blue
        ])

    def _set_coordinates(self, x:int=0, y:int=0) -> str:
        ''' Call to SET XY in the DLL '''
        return self.send_command([
            'SET', 'XY', x, y
        ])

    def _set_textinfo_target(self, idx:Union[int, None]=None) -> str:
        ''' Call to SET TEXTINFO_TARGET in the DLL. Passing an index of None will lead to the last TextInfo being targeted '''
        if idx is None:
            return self.send_command(["SET", "TEXTINFO_TARGET"])
        else:
            return self.send_command(["SET", "TEXTINFO_TARGET", str(idx)])

    def _get_text(self) -> str:
        ''' Call to GET TEXT in the DLL '''
        return self.send_command(["GET", "TEXT"], check_ok=False)

    def _get_color(self) -> Color:
        ''' Call to GET RGB in the DLL '''
        r, g, b = self.send_command(["GET", "RGB"], check_ok=False).split(',')
        return Color(r, g, b)

    def _get_coordinates(self) -> Size:
        ''' Call to GET XY in the DLL '''
        x, y = self.send_command(["GET", "XY"], check_ok=False).split(',')
        return Size(x, y)

    def _get_textinfo_target(self) -> Union[int, None]:
        ''' Call to GET TEXTINFO_TARGET in the DLL. A return of None, means that the current target is the last TextInfo.'''
        # Cheap use of eval. It can be 'None' or an int.
        return eval(self.send_command(["GET", "TEXTINFO_TARGET"], check_ok=False))

    def __test(self):
        ''' a test... that is broken at the moment :) '''
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

class TextInfo:
    '''
    Represents a reference to a TextInfo object in the DLL.

    A TextInfo is a specific line/piece of text with a specific X/Y, RGB color, and text.
    '''
    def __init__(self, control_pipe:ControlPipe, idx:int):
        self.controlPipe = control_pipe
        self._idx = idx

    @contextlib.contextmanager
    def targeting_this_textinfo(self):
        previous_target = self.controlPipe._get_textinfo_target()
        self.controlPipe._set_textinfo_target(self._idx)
        try:
            yield
        finally:
            self.controlPipe._set_textinfo_target(previous_target)

    def set_text(self, text:str) -> None:
        ''' Sets the text of this TextInfo '''
        with self.targeting_this_textinfo():
            self.controlPipe._set_text(text)

    def set_color(self, red:int=255, green:int=255, blue:int=255) -> None:
        ''' Sets the color of this TextInfo '''
        with self.targeting_this_textinfo():
            self.controlPipe._set_color(red, green, blue)

    def set_coordinates(self, x:int=0, y:int=0) -> None:
        ''' Sets the X/Y coordinates of this TextInfo '''
        with self.targeting_this_textinfo():
            self.controlPipe._set_coordinates(x, y)

    def get_text(self) -> str:
        ''' Gets the text of this TextInfo '''
        with self.targeting_this_textinfo():
            return self.controlPipe._get_text()

    def get_color(self) -> Color:
        ''' Gets the color of this TextInfo '''
        with self.targeting_this_textinfo():
            return self.controlPipe._get_color()

    def get_coordinates(self) -> Size:
        ''' Gets the X/Y coordinates of this TextInfo '''
        with self.targeting_this_textinfo():
            return self.controlPipe._get_coordinates()

    def get_text_size(self) -> Size:
        ''' Gets the pixel size of the text within this TextInfo '''
        text = self.get_text()
        return self.controlPipe.get_text_size(text)
