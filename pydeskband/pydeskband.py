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
        try:
            with open(_LogTailer.LOG_PATH, 'rb') as log_file:
                log_file.seek(self.starting_offset)
                while not self.exit_event.is_set():
                    line = log_file.readline().rstrip().decode()
                    if line:
                        print(line, file=sys.stderr)
                    time.sleep(.01)
        except KeyboardInterrupt:
            pass

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

    def send_command(self, cmd:Union[list, tuple, str], check_ok:bool=True) -> list:
        '''
        The main entry point to go from Python to/from the C++ code. It is very unlikely that a regular user
        would want to call this directly. If something is done incorrectly here, PyDeskband will likely crash...
            and that will lead to Windows Explorer restarting.

        Arguments:
            cmd: Either a list of command keywords or a string of a full command
            check_ok: If True, raise ValueError if C++ does not give back "OK" as the return status.
                If set, will remove OK from the return list.

        Returns:
            A list of return fields.
        '''
        if isinstance(cmd, (list, tuple)):
            cmd = ','.join([str(c) for c in cmd])

        cmd = cmd.encode()

        bytes_written = self.pipe.write(cmd)
        if bytes_written != len(cmd):
            raise RuntimeError(f"Unable to write all the bytes down the pipe. Wrote: {bytes_written} instead of {len(cmd)}")

        response = self.pipe.readline().strip().decode().split(',')

        if not response:
            raise ValueError("Response was empty.")

        if check_ok:
            if response[0] != 'OK':
                raise ValueError(f"Response was not OK. It was: {response[0]}")
            response = response[1:]

        return response

    def get_width(self) -> int:
        ''' Get the current width (in pixels) of the deskband '''
        return int(self.send_command(['GET', 'WIDTH'])[0])

    def get_height(self) -> int:
        ''' Get the current height (in pixels) of the deskband '''
        return int(self.send_command(['GET', 'HEIGHT'])[0])

    def get_text_info_count(self) -> int:
        ''' Get the count of TextInfos currently saved '''
        return int(self.send_command(['GET', 'TEXTINFOCOUNT'])[0])

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
        ], check_ok=False)[:2]
        return Size(x, y)

    def paint(self) -> None:
        ''' Requests that PyDeskband repaint all TextInfos now '''
        self.send_command('PAINT')

    def clear(self, reset_target_textinfo:bool=True) -> None:
        '''
        Clears all TextInfos and re-paints.

        If reset_target_textinfo is set, will also reset the current TextInfo target.
        '''
        self.send_command('CLEAR')
        self._set_textinfo_target()

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

    def get_transport_version(self) -> int:
        '''
        Gets the current transport version from the DLL.
        '''
        return int(self.send_command([
            'GET', 'TRANSPORT_VERSION'
        ])[0])

    def set_windows_message_handle_shell_cmd(self, msg_id:int, shell_cmd:str=None) -> None:
        ''' Tell PyDeskband that if msg_id is sent to the form, run this shell command. If shell_cmd is None, clear existing handling of the msg_id. '''
        if shell_cmd is not None:
            return self.send_command([
                'SET', 'WIN_MSG', msg_id, self._verify_input_text(shell_cmd)
            ])
        else:
            return self.send_command([
                'SET', 'WIN_MSG', msg_id
            ])

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
        return self.send_command(["GET", "TEXT"])[0]

    def _get_color(self) -> Color:
        ''' Call to GET RGB in the DLL '''
        r, g, b = self.send_command(["GET", "RGB"])[:3]
        return Color(r, g, b)

    def _get_coordinates(self) -> Size:
        ''' Call to GET XY in the DLL '''
        x, y = self.send_command(["GET", "XY"])[:2]
        return Size(x, y)

    def _get_textinfo_target(self) -> Union[int, None]:
        ''' Call to GET TEXTINFO_TARGET in the DLL. A return of None, means that the current target is the last TextInfo.'''
        # Cheap use of eval. It can be 'None' or an int.
        return eval(self.send_command(["GET", "TEXTINFO_TARGET"])[0])

    def _test(self):
        ''' a test... :) '''
        import psutil, time

        def get_mbps_down():
            last_timestamp = getattr(get_mbps_down, 'last_timestamp', time.time())
            last_bytes = getattr(get_mbps_down, 'last_bytes', 0)

            get_mbps_down.last_bytes = psutil.net_io_counters().bytes_recv

            now = time.time()
            mbps = (get_mbps_down.last_bytes - float(last_bytes)) / 125000.0 /  (now - last_timestamp)
            get_mbps_down.last_timestamp = now
            return mbps

        def get_mbps_up():
            last_timestamp = getattr(get_mbps_up, 'last_timestamp', time.time())
            last_bytes = getattr(get_mbps_up, 'last_bytes', 0)

            get_mbps_up.last_bytes = psutil.net_io_counters().bytes_sent

            now = time.time()
            mbps = (get_mbps_up.last_bytes - float(last_bytes)) / 125000.0 /  (now - last_timestamp)
            get_mbps_up.last_timestamp = now
            return mbps

        def get_cpu_used_percent():
            return psutil.cpu_percent()

        self.clear()

        # Left click: Open task manager
        self.set_windows_message_handle_shell_cmd(0x0201, r'start C:\Windows\System32\Taskmgr.exe')
        cpuTextInfo = self.add_new_text_info('')
        netDownTextInfo = self.add_new_text_info('', y=20)

        while True:
            cpu = get_cpu_used_percent()
            cpuTextInfo.set_text(f'CPU: {cpu}%')
            netDownTextInfo.set_text(f'Net: {get_mbps_down():.02f}/{get_mbps_up():.02f} Mbps')
            self.paint()
            time.sleep(1)

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
