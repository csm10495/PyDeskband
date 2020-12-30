from setuptools import setup
from setuptools.command.build_py import build_py

import glob
import os
import pathlib
import shutil
import subprocess
import sys

THIS_FOLDER = os.path.abspath(os.path.dirname(__file__))

def getVersion():
    with open(os.path.join(THIS_FOLDER, 'pydeskband', '__init__.py'), 'r') as f:
        text = f.read()

    for line in text.splitlines():
        if line.startswith('__version__'):
            version = line.split('=', 1)[1].replace('\'', '').replace('"', '')
            return version.strip()

    raise EnvironmentError("Unable to find __version__!")

def get_msbuild():
    matches = glob.glob(r'C:\Program Files*\Microsoft Visual Studio\2019\*\MSBuild\*\Bin\MSBuild.exe')
    if matches:
        print(f"MSBuild: {matches[0]}")
        return pathlib.Path(matches[0])

    raise EnvironmentError("Could not find MSBuild for VS 2019!")

def get_sln():
    sln = pathlib.Path(THIS_FOLDER) / "dll/PyDeskband/PyDeskband.sln"
    if not sln.is_file():
        raise FileNotFoundError(f"Could not find sln file: {sln}")

    return sln

def run_msbuild(configuration, platform):
    if configuration not in ('Debug', 'Release'):
        raise ValueError("configuration should be Debug or Release")
    if platform not in ('x64', 'x86'):
        raise ValueError("platform should be x64 or x86")

    if subprocess.check_call([
        get_msbuild(),
        get_sln(),
        f'/p:Configuration={configuration}',
        f'/p:Platform={platform}',
    ]) == 0:
        arch_folder = 'x64' if platform == 'x64' else ''
        output = pathlib.Path(THIS_FOLDER) / f"dll/PyDeskband/{arch_folder}/{configuration}/PyDeskband.dll"
        if not output.is_file():
            raise FileNotFoundError("MSBuild was successful, though we couldn't find the output dll.")
        return output

class BuildPyCommand(build_py):
    """Custom build command. That will build dlls using MSBuild"""
    def build_and_copy_dlls(self):
        # Build x64 and x86 versions of the dll
        x64_dll = run_msbuild('Release', 'x64')
        x86_dll = run_msbuild('Release', 'x86')

        dll_dir = pathlib.Path(THIS_FOLDER) / "pydeskband/dlls"
        if not dll_dir.is_dir():
            dll_dir.mkdir()

        # copy dlls to dll dir
        shutil.copy(x64_dll, dll_dir / "PyDeskband_x64.dll")
        shutil.copy(x86_dll, dll_dir / "PyDeskband_x86.dll")

        print("DLLs have been copied!")

    def run(self):
        self.build_and_copy_dlls()
        build_py.run(self)

setup(
    name='pydeskband',
    author='csm10495',
    author_email='csm10495@gmail.com',
    url='http://github.com/csm10495/pydeskband',
    version=getVersion(),
    packages=['pydeskband'],
    license='MIT License',
    python_requires='>=3,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*,!=3.5.*,!=3.6.*',
    long_description=open(os.path.join(os.path.dirname(__file__), 'README.md')).read(),
    long_description_content_type="text/markdown",
    classifiers=[
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Operating System :: Microsoft :: Windows',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
    ],
    package_data={
        "pydeskband": ["dlls/*.dll"],
    },
    cmdclass={
        'build_py': BuildPyCommand
    },
    install_requires=[],
)