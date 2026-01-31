# 🖥️ Monitor Input Switcher

*A Windows desktop application for managing multiple monitors with fast input switching, global shortcuts, and system tray control.*

Monitor Input Switcher simplifies working with multi-monitor setups by allowing users to switch monitor input sources, manage layouts, and control displays directly from the keyboard or system tray. Built with Python and a modern CustomTkinter UI, it focuses on productivity, automation, and seamless Windows integration.

---

## 🚀 Project Overview

Monitor Input Switcher is designed for users who frequently switch between multiple devices (PCs, laptops, consoles) connected to the same monitors. Instead of using physical monitor buttons, the application leverages **DDC/CI**, **global hotkeys**, and **Windows APIs** to provide fast, software-based monitor control.

The project supports configurable shortcuts, persistent user preferences, tray-based operation, and optional startup behavior—making it ideal for power users and multi-device workstations.

---

## 🛠️ Tech Stack

* **Python 3.8+** – Core application logic
* **CustomTkinter** – Modern, themed desktop UI
* **monitorcontrol** – DDC/CI monitor input control
* **keyboard** – Global keyboard shortcut handling
* **pystray** – System tray integration
* **screeninfo** – Monitor detection and metadata
* **pywin32** – Windows API & registry access
* **WMI** – Windows system management
* **Pillow** – Icon and image handling

---

## 🎯 Key Features

### 🖥️ Multi-Monitor Management

* Automatic detection of connected monitors
* Support for HDMI, DisplayPort, USB-C, and other inputs
* Individual control per monitor

### 🔄 Input Source Switching

* Instantly change monitor input sources via software
* No need to use physical monitor buttons
* Works with DDC/CI–compatible monitors

### ⌨️ Keyboard Shortcuts

* Fully customizable global hotkeys
* Switch inputs, toggle monitors, or load presets
* Works even when the app is minimized

### 💾 Configuration Management

* Save and restore user preferences
* Persistent shortcuts and monitor layouts
* JSON-based configuration files

### 🔔 System Tray Integration

* Run silently in the background
* Quick-access tray menu
* One-click show/hide behavior

### 🎨 Modern UI & Theming

* Clean CustomTkinter interface
* Light and dark mode support
* Responsive and user-friendly layout

### 🪟 Windows Integration

* Optional startup on boot
* Registry-based configuration
* Native Windows behavior

---

## 📁 Project Structure

```
KaizenV3.1/
│
├─ assets/                     # Icons and UI resources
│
├─ config/
│   └─ default_config.json     # Default settings
│
├─ logs/
│   └─ monitor_manager.log     # Application logs
│
├─ ui/
│   ├─ main_window.py          # Main application UI
│   └─ tray.py                 # System tray logic
│
├─ services/
│   ├─ monitor_service.py      # DDC/CI monitor control
│   ├─ shortcut_service.py     # Global hotkey handling
│   └─ config_service.py       # Config load/save logic
│
├─ monitor_manager.py          # Application entry point
├─ requirements.txt            # Python dependencies
└─ README.md
```

---

## 🚀 Getting Started

### Prerequisites

* Windows 10 or later
* Python 3.8 or higher
* Monitors that support **DDC/CI**

### Installation

Clone the repository:

```bash
git clone <repository-url>
cd KaizenV3.1
```

Create and activate a virtual environment:

```bash
python -m venv venv
venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## ▶️ Usage

### Running the Application

```bash
python monitor_manager.py
```

### Keyboard Shortcuts

Configure shortcuts in the application to:

* Switch monitor input sources
* Toggle between monitors
* Load frequently used configurations

### System Tray

* Left-click: Show / hide main window
* Right-click: Access quick actions and settings

The app can remain running in the background without interrupting workflow.

---

## ⚙️ Configuration

User configuration files are stored at:

```
%APPDATA%\monitor_manager\
```

Included files:

* `monitor_manager.log` – Application logs
* User preferences and shortcuts (JSON format)

---

## 📦 Building a Standalone Executable

To build a Windows executable:

```bash
pyinstaller --onefile --windowed --icon=icon.ico monitor_manager.py
```

The compiled `.exe` will be available in the `dist/` directory.

---

## 🛠️ Troubleshooting

### Monitor Not Detected

* Ensure the monitor supports **DDC/CI**
* Check cable connections
* Try running the app as Administrator

### Keyboard Shortcuts Not Working

* Check for shortcut conflicts
* Ensure keyboard permissions are granted
* Try running as Administrator

### Application Won’t Start

* Check logs at:

  ```
  %APPDATA%\monitor_manager\monitor_manager.log
  ```
* Verify Python version (3.8+)
* Ensure all dependencies are installed

---

## 🤝 Contributing

Contributions are welcome!

1. Fork the repository
2. Create a feature branch

   ```bash
   git checkout -b feature/AmazingFeature
   ```
3. Commit your changes
4. Push to your branch
5. Open a Pull Request

---

## 📄 License

This project is licensed under the **MIT License**.
See the [LICENSE](LICENSE) file for details.

---

## 📞 Support

* Open an issue on GitHub for bugs or feature requests
* Contact the maintainer for questions or feedback

Happy switching! 🚀

---

If you want next:

* 🔹 A **shorter recruiter-friendly README**
* 🔹 Badges (Python version, OS, license)
* 🔹 Screenshots section
* 🔹 GitHub “About” + tags optimization

Just say the word.
