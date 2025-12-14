# Monitor Manager

A Windows application for managing multiple monitors with customizable input switching, keyboard shortcuts, and system tray integration.

## Features

- 🖥️ **Multi-Monitor Support** - Detect and manage multiple monitors
- 🔄 **Input Source Switching** - Quick switching between HDMI, DisplayPort, USB-C, and other input sources
- ⌨️ **Keyboard Shortcuts** - Customizable global hotkeys for instant monitor control
- 🎨 **Modern UI** - Clean interface built with CustomTkinter
- 💾 **Configuration Management** - Save and load monitor layouts and preferences
- 🔔 **System Tray Integration** - Minimize to tray with quick access menu
- 🌓 **Theme Support** - Dark and light mode options
- 🪟 **Windows Integration** - Startup configuration and registry management

## Requirements

- Windows 10 or later
- Python 3.8+

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd KaizenV3.1
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Running the Application

```bash
python monitor_manager.py
```

### Keyboard Shortcuts

Configure custom keyboard shortcuts in the application to:
- Switch monitor input sources
- Toggle between monitors
- Quick access to frequently used configurations

### System Tray

The application can run in the system tray for quick access:
- Right-click the tray icon for options
- Left-click to show/hide the main window

## Configuration

Configuration files are stored in:
- Windows: `%APPDATA%\monitor_manager\`

Files include:
- `monitor_manager.log` - Application logs
- User shortcuts and preferences (JSON format)

## Building Executable

To create a standalone executable:

1. Ensure PyInstaller is installed (included in requirements.txt)
2. Run the build command:
```bash
pyinstaller --onefile --windowed --icon=icon.ico monitor_manager.py
```

The executable will be created in the `dist` folder.

## Dependencies

Main dependencies:
- **customtkinter** - Modern UI framework
- **monitorcontrol** - DDC/CI monitor control
- **keyboard** - Global keyboard hooks
- **pystray** - System tray integration
- **screeninfo** - Display information
- **pywin32** - Windows API access
- **WMI** - Windows Management Instrumentation
- **Pillow** - Image processing

See [requirements.txt](requirements.txt) for complete list with versions.

## Troubleshooting

### Monitor Not Detected
- Ensure monitors support DDC/CI
- Check monitor cables are properly connected
- Try running the application as administrator

### Keyboard Shortcuts Not Working
- Check if shortcuts conflict with other applications
- Verify keyboard module has proper permissions
- Try running as administrator

### Application Won't Start
- Check log file in `%APPDATA%\monitor_manager\monitor_manager.log`
- Ensure all dependencies are installed
- Verify Python version is 3.8 or higher

## License

[Add your license information here]

## Contributing

[Add contribution guidelines here]

## Support

For issues and feature requests, please [create an issue](link-to-issues) or contact the maintainer.
