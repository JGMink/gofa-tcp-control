Python version:
    Python 3.9 - 3.12 recommended

PortAudio required for sounddevice:
```bash
    pip install sounddevice
```
for macOS:
```bash
    brew install portaudio
```

for Linus:
```bash
    sudo apt-get install protaudio19-dev
```

## Azure Resources required:

The program will not run fully unless the user has:
 * Azure Speech resource
 * Azure Language / CLU resource
 * Valid keys & endpoints

## Microsoft Building tools are also a required:
Microsoft C++ Build Tools - Visual Studio:
 * MSVC v143 - VS 2022 C++ x64/x86 build tools 
 * Windows 10 or 11 SDK
 * C++ CMake tools for Windows (optional but recommended)
 
 ```bash
 powershell -Command "Invoke-WebRequest https://aka.ms/vs/17/release/vs_BuildTools.exe -OutFile vs_BuildTools.exe; Start-Process .\vs_BuildTools.exe -Wait -ArgumentList '--quiet --norestart --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --add Microsoft.VisualStudio.Component.Windows10SDK --add Microsoft.VisualStudio.Component.VC.CMake.Project'"
```


## Installation

```bash
pip install -r requirements.txt
```


