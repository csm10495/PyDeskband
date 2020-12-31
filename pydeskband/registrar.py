import argparse
import os
import ctypes
import pathlib
import subprocess

class RegistrarActionRequiresAdmin(PermissionError):
    ''' Used to denote that this action requires admin permissions '''
    pass

class Registrar:
    ''' A collection of methods relating to registering and unregistering PyDeskband via regsvr32.exe '''
    @classmethod
    def is_64_bit(cls) -> bool:
        return '64' in subprocess.check_output([
            'wmic', 'os', 'get', 'osarchitecture'
        ]).decode()

    @classmethod
    def is_admin(cls) -> bool:
        ''' Asks Windows if we are running as admin '''
        return bool(ctypes.windll.shell32.IsUserAnAdmin())

    @classmethod
    def get_dll_path(cls) -> pathlib.Path:
        ''' Returns the path to the PyDeskband dll for the OS architecture '''
        arch = '64' if cls.is_64_bit() else '86'
        dll_path = (pathlib.Path(__file__).parent / f"dlls/PyDeskband_x{arch}.dll").resolve()
        if not dll_path.is_file():
            raise FileNotFoundError(f"dll_path: {dll_path} is missing")
        return dll_path

    @classmethod
    def get_regsvr32_path(cls) -> pathlib.Path:
        ''' Returns the path to regsvr32.exe '''
        path = pathlib.Path(os.path.expandvars(r'%systemroot%\System32\regsvr32.exe'))
        if not path.is_file():
            raise FileNotFoundError(f"regsvr32.exe {path} is missing")
        return path

    @classmethod
    def register(cls) -> int:
        '''
        Attempts to register the PyDeskband DLL with the OS. Will return the exit code from that attempt. 0 typically means success.
        Requires admin privledges to run.

        Funny enough, on register, you may need to view right click and view the Toolbars list twice before the option PyDeskband option comes up.
            (This is even if you restart Windows Explorer). This is a known Windows behavior and not a bug with PyDeskband.
        '''
        if not cls.is_admin():
            raise RegistrarActionRequiresAdmin("Registering pyDeskband requires admin permissions!")

        return subprocess.call([cls.get_regsvr32_path(), cls.get_dll_path(), '/s'])

    @classmethod
    def unregister(cls) -> int:
        '''
        Attempts to unregister the PyDeskband DLL with the OS. Will return the exit code from that attempt. 0 typically means success.
        Requires admin privledges to run.
        '''
        if not cls.is_admin():
            raise RegistrarActionRequiresAdmin("Unregistering pyDeskband requires admin permissions!")

        return subprocess.call([cls.get_regsvr32_path(), '/u', cls.get_dll_path(), '/s'])

    @classmethod
    def restart_windows_explorer(cls) -> None:
        '''
        Uses the knowledge of us being on Windows to use a subprocess to restart Windows Explorer.

        Technically a Windows Explorer restart is not necessary though on an unregister, it will force the dll to be unloaded.
        '''
        subprocess.call('taskkill /F /IM explorer.exe && start explorer', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="CLI to register/unregister PyDeskband with the registry")
    action = parser.add_mutually_exclusive_group()
    action.add_argument('-r', '--register', help='Registers the PyDeskband DLL with the OS.', action='store_true')
    action.add_argument('-u', '--unregister', help='Unregisters the PyDeskband DLL with the OS. Unless -x/--no-restart-explorer is given, Windows Explorer will restart after success.', action='store_true')
    parser.add_argument('-x', '--no-restart-explorer', help='If given, do not restart Windows Explorer after registering or unregistering.', action='store_true')
    args = parser.parse_args()

    ret_code = None
    if args.register:
        ret_code = Registrar.register()
    elif args.unregister:
        ret_code = Registrar.unregister()

    if ret_code is not None:
        if ret_code == 0 and not args.no_restart_explorer:
            Registrar.restart_windows_explorer()
        exit(ret_code)
