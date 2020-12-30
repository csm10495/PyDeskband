# PyDeskband

PyDeskband is a multi-part project with two interconnected pieces of code.

## C++

There is a C++ DLL that is loaded via regsvr32.exe (into Windows Explorer) to create and paint a Deskband on the Windows Taskbar.

## Python

The Python front-end contains a means to control the C++ backend to control what is painted onto the Deskband. After installing the dll, it's easy to manipulate the deskband:

<img src="https://i.imgur.com/TJkWOhb.png">

# What is a Deskband?

A Deskband is an additonal toolbar placed on the right-hand-side of the Windows Taskbar. Interestingly, enough they are considered deprecated as of Windows 10, but as of this writing still work just fine. Here is some [documentation](https://docs.microsoft.com/en-us/previous-versions/windows/desktop/legacy/cc144099(v=vs.85)) that includes high-level information on Deskbands.

## Any Other Deskband Examples?

Another example of a deskband is [XMeters](https://entropy6.com/xmeters/)

## License
MIT License