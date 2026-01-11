import customtkinter
from monitorcontrol import get_monitors, InputSource
import platform
import logging
import threading
import os
import sys
import shutil
from pathlib import Path
import keyboard
import json
from tkinter import messagebox
from screeninfo import get_monitors as get_screen_info

# Available themes for customtkinter
AVAILABLE_THEMES = ["dark", "light"]

# Import WMI only on Windows
if platform.system() == 'Windows':
    import wmi
    import pythoncom

# Set up logging
logging.basicConfig(filename='monitor_manager.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Manufacturer codes from PnP IDs
PNP_IDS = {
    "AAC": "Acer", "ACR": "Acer", "AOC": "AOC", "AUO": "AU Optronics",
    "BNQ": "BenQ", "CMO": "Chi Mei", "DEL": "Dell", "HEI": "Hisense",
    "HPN": "HP", "HSD": "Hisense", "HWP": "HP", "IVM": "Iiyama",
    "LGD": "LG Display", "LPL": "LG Philips", "NEC": "NEC", "SAM": "Samsung",
    "SEC": "Samsung", "SNY": "Sony", "TCL": "TCL", "TOS": "Toshiba",
    "TPV": "TPV", "VSC": "ViewSonic", "GGL": "Google", "MSI": "MSI",
    "GIG": "Gigabyte", "RAZ": "Razer",
}

# Fallback brand detection from model
MODEL_BRAND_MAP = {
    # ASUS monitors
    "PA": "ASUS", "PG": "ASUS", "VG": "ASUS", "MG": "ASUS", "ROG": "ASUS", 
    "TUF": "ASUS", "XG": "ASUS", "BE": "ASUS", "VP": "ASUS",
    
    # Dell/Alienware monitors
    "AW": "Alienware", "U": "Dell", "P": "Dell", "S": "Dell", "E": "Dell",
    
    # LG monitors
    "LG": "LG", "MP": "LG", "GP": "LG", "OLED": "LG", "GL": "LG", 
    "GN": "LG", "UK": "LG", "UM": "LG",
    
    # Samsung monitors
    "C": "Samsung", "G": "Samsung", "ODYSSEY": "Samsung", "S": "Samsung",
    "U": "Samsung", "F": "Samsung", "LS": "Samsung",
    
    # AOC monitors
    "27G": "AOC", "24G": "AOC", "22": "AOC", "Q27": "AOC", "CQ": "AOC",
    "C24": "AOC", "C27": "AOC", "C32": "AOC", "AG": "AOC", "AGON": "AOC",
    
    # ViewSonic monitors
    "VX": "ViewSonic", "XG": "ViewSonic", "VA": "ViewSonic", "VP": "ViewSonic",
    
    # BenQ monitors
    "XL": "BenQ", "EX": "BenQ", "PD": "BenQ", "EW": "BenQ", "ZOWIE": "BenQ",
    
    # Acer monitors
    "XV": "Acer", "XF": "Acer", "KG": "Acer", "CB": "Acer", "XB": "Acer",
    "NITRO": "Acer", "PREDATOR": "Acer",
    
    # MSI monitors
    "MAG": "MSI", "MPG": "MSI", "OPTIX": "MSI", "MEG": "MSI",
    
    # Gigabyte monitors
    "FI": "Gigabyte", "M": "Gigabyte", "G27": "Gigabyte", "AORUS": "Gigabyte",
    
    # HP monitors
    "OMEN": "HP", "X27": "HP", "Z27": "HP", "PAVILION": "HP",
    
    # Philips monitors
    "BDM": "Philips", "PHL": "Philips", "PHI": "Philips"
}

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def get_user_config_dir():
    """Return a writable config directory for storing user data (shortcuts, settings).

    On Windows this returns %APPDATA%\monitor_manager, otherwise ~/.config/monitor_manager
    """
    app_name = 'monitor_manager'
    home = Path.home()
    try:
        if platform.system() == 'Windows':
            appdata = os.getenv('APPDATA')
            if not appdata:
                appdata = str(home / 'AppData' / 'Roaming')
            return os.path.join(appdata, app_name)
        else:
            return os.path.join(str(home), '.config', app_name)
    except Exception:
        # Fallback to current working directory
        return os.path.abspath('.')

class App(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        self.title("Monitor Input Switcher v0.0.8")
        self.geometry("500x400")  # Made window slightly taller
        self.iconbitmap(resource_path('monitor_manager_icon.ico'))

        # Default shortcut configuration
        self.default_shortcuts = {
            'ctrl+shift+1': (0, 'HDMI1'),  # Monitor 0, HDMI1
            'ctrl+shift+2': (0, 'DP1'),    # Monitor 0, DP1
            'ctrl+shift+3': (1, 'HDMI1'),  # Monitor 1, HDMI1
            'ctrl+shift+4': (1, 'DP1'),    # Monitor 1, DP1
        }
        
        # Determine persistent location for shortcuts (per-user config dir)
        config_dir = get_user_config_dir()
        try:
            os.makedirs(config_dir, exist_ok=True)
        except Exception:
            pass

        # default path in user config dir
        self.shortcuts_file = os.path.join(config_dir, 'custom_shortcuts.json')

        # Favorites file in same config dir
        self.favorites_file = os.path.join(config_dir, 'favorites.json')

        # Settings file (theme and accent color)
        self.settings_file = os.path.join(config_dir, 'settings.json')

        # If an old shortcuts file exists alongside the script (e.g., when running in dev), migrate it
        old_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'custom_shortcuts.json')
        try:
            if os.path.exists(old_path) and not os.path.exists(self.shortcuts_file):
                shutil.copy2(old_path, self.shortcuts_file)
                logging.info(f"Migrated shortcuts file from {old_path} to {self.shortcuts_file}")
        except Exception as e:
            logging.debug(f"Could not migrate old shortcuts file: {e}")
        self.shortcuts = self.load_shortcuts() or self.default_shortcuts
        self.favorites = self.load_favorites() or {}
        
        # Load and apply theme settings
        self.settings = self.load_settings() or {"theme": "dark"}
        self.apply_theme()
        
        # Setup global hotkeys
        self.setup_global_hotkeys()

        self.main_frame = customtkinter.CTkFrame(self)
        self.main_frame.pack(pady=20, padx=20, fill="both", expand=True)

        self.monitor_label = customtkinter.CTkLabel(self.main_frame, text="Select a monitor:")
        self.monitor_label.pack(pady=(0, 5))

        self.monitor_menu = customtkinter.CTkOptionMenu(self.main_frame, values=["Loading..."], command=self.update_inputs)
        self.monitor_menu.set("Loading...")
        self.monitor_menu.pack(pady=(0, 10), fill="x", padx=20)

        self.input_label = customtkinter.CTkLabel(self.main_frame, text="Select an input source:")
        self.input_label.pack(pady=(10, 5))

        self.input_menu = customtkinter.CTkOptionMenu(self.main_frame, values=["Loading..."])
        self.input_menu.set("Loading...")
        self.input_menu.pack(pady=(0, 20), fill="x", padx=20)

        self.progress_bar = customtkinter.CTkProgressBar(self.main_frame, mode='indeterminate')

        self.button_frame = customtkinter.CTkFrame(self)
        self.button_frame.pack(pady=(0, 20), padx=20, fill="x")

        self.switch_button = customtkinter.CTkButton(self.button_frame, text="Switch Input", command=self.switch_input)
        self.switch_button.pack(side="left", padx=(0, 10), expand=True)

        self.refresh_button = customtkinter.CTkButton(self.button_frame, text="Refresh", command=self.refresh_monitors)
        self.refresh_button.pack(side="right", padx=(10, 0), expand=True)

        # Add button frame for shortcuts and settings
        self.control_frame = customtkinter.CTkFrame(self)
        self.control_frame.pack(pady=(5, 5), padx=20, fill="x")

        # Add Customize Shortcuts button (disabled until monitors are loaded)
        self.shortcuts_button = customtkinter.CTkButton(self.control_frame, text="Customize Shortcuts", command=self.show_shortcuts_editor, state="disabled")
        self.shortcuts_button.pack(side="left", padx=(0, 10), expand=True)

        # Add Theme Settings button
        self.theme_button = customtkinter.CTkButton(self.control_frame, text="Theme", command=self.show_theme_settings)
        self.theme_button.pack(side="right", padx=(10, 0), expand=True)

        # Add Favorites section
        self.favorites_label = customtkinter.CTkLabel(self, text="Quick Favorites:", font=("Arial", 10, "bold"))
        self.favorites_label.pack(pady=(10, 5), padx=20)

        self.favorites_frame = customtkinter.CTkFrame(self)
        self.favorites_frame.pack(fill="x", padx=20, pady=(0, 5))

        # Manage favorites button
        self.manage_favorites_btn = customtkinter.CTkButton(self, text="Manage Favorites", command=self.show_manage_favorites, state="disabled")
        self.manage_favorites_btn.pack(pady=(0, 5))

        self.status_label = customtkinter.CTkLabel(self, text="", wraplength=480)
        self.status_label.pack(pady=(0, 10), padx=20)

        self.name_label = customtkinter.CTkLabel(self, text="By: LuqmanHakimAmiruddin@PDC", font=("Arial", 10))
        self.name_label.pack(pady=(5, 10))

        self.refresh_monitors()

    def refresh_monitors(self):
        self.status_label.configure(text="Fetching all monitors info...")
        self.progress_bar.pack(pady=(10, 10), fill="x", padx=20)
        self.progress_bar.start()

        self.switch_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")

        self.monitor_menu.configure(values=["Loading..."])
        self.monitor_menu.set("Loading...")
        self.input_menu.configure(values=["Loading..."])
        self.input_menu.set("Loading...")

        thread = threading.Thread(target=self.load_monitor_data_thread)
        thread.start()

    def load_monitor_data_thread(self):
        if platform.system() == 'Windows':
            pythoncom.CoInitialize()
        try:
            self.monitors_data = self.get_all_monitor_data()
        finally:
            if platform.system() == 'Windows':
                pythoncom.CoUninitialize()
        self.after(0, self.update_ui_after_load)

    def update_ui_after_load(self):
        self.monitor_names = [data['display_name'] for data in self.monitors_data]
        
        self.monitor_menu.configure(values=self.monitor_names)
        if self.monitor_names:
            self.monitor_menu.set(self.monitor_names[0])
            self.update_inputs(self.monitor_names[0])
            self.status_label.configure(text="Ready.")
            # Enable shortcuts customization once monitors are known
            try:
                self.shortcuts_button.configure(state="normal")
                self.manage_favorites_btn.configure(state="normal")
            except Exception:
                pass
            # Build favorites buttons
            self.refresh_favorites_buttons()
        else:
            self.monitor_menu.set("No monitors found")
            self.input_menu.configure(values=[])
            self.input_menu.set("")
            self.status_label.configure(text="No monitors found. Please check connections.")
            try:
                self.shortcuts_button.configure(state="disabled")
                self.manage_favorites_btn.configure(state="disabled")
            except Exception:
                pass

        self.progress_bar.stop()
        self.progress_bar.pack_forget()

        self.switch_button.configure(state="normal")
        self.refresh_button.configure(state="normal")

    def get_all_monitor_data(self):
        all_data = []

        try:
            monitors = get_monitors()
            logging.info(f"Found {len(monitors)} monitors.")
            
            # Get display adapter information on Windows
            if platform.system() == "Windows":
                try:
                    c = wmi.WMI()
                    video_controllers = c.Win32_VideoController()
                    for controller in video_controllers:
                        logging.info(f"Display adapter: {controller.Name}, Status: {controller.Status}")
                        logging.info(f"Adapter RAM: {controller.AdapterRAM if hasattr(controller, 'AdapterRAM') else 'Unknown'}")
                        if hasattr(controller, 'VideoProcessor'):
                            logging.info(f"Video Processor: {controller.VideoProcessor}")
                except Exception as e:
                    logging.warning(f"Could not get display adapter info: {e}")
                    
        except Exception as e:
            logging.error(f"Could not get monitors: {e}")
            return []

        # Get detailed monitor and connection information
        pnp_ids = []
        connection_info = {}
        if platform.system() == "Windows":
            try:
                c = wmi.WMI()
                
                # Get monitor information
                wmi_monitors = c.Win32_DesktopMonitor()
                for monitor in wmi_monitors:
                    pnp_ids.append(getattr(monitor, 'PNPDeviceID', None))
                logging.info(f"WMI PnP IDs: {pnp_ids}")
                
                # Get video controller information
                video_controllers = c.Win32_VideoController()
                for controller in video_controllers:
                    logging.info(f"Display adapter: {controller.Name}")
                    logging.info(f"Adapter DAC Type: {controller.AdapterDACType if hasattr(controller, 'AdapterDACType') else 'Unknown'}")
                    logging.info(f"Video Architecture: {controller.VideoArchitecture if hasattr(controller, 'VideoArchitecture') else 'Unknown'}")
                    
                # Get USB controller information (for USB-C/TB detection)
                usb_controllers = c.Win32_USBController()
                for controller in usb_controllers:
                    if "type-c" in controller.Name.lower() or "thunderbolt" in controller.Name.lower():
                        logging.info(f"Found USB-C/Thunderbolt controller: {controller.Name}")
                        
                # Get physical media connection types
                physical_media = c.Win32_PhysicalMedia()
                for media in physical_media:
                    if hasattr(media, 'Tag') and 'display' in media.Tag.lower():
                        logging.info(f"Physical display connection: {media.Tag}")
                        
            except Exception as e:
                logging.error(f"Failed to get device information from WMI: {e}")

        # EDID Reader (Windows only)
        def read_edid(pnp_id):
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Enum\\" + pnp_id + r"\Device Parameters"
                )
                edid_data, _ = winreg.QueryValueEx(key, "EDID")
                return edid_data
            except Exception:
                return None

        def parse_edid(edid):
            try:
                model = "".join(chr(c) for c in edid[54:72] if 32 <= c <= 126).strip()
                return model if model else "Unknown"
            except Exception:
                return "Unknown"

        for i, monitor_obj in enumerate(monitors):

            # Skip internal laptop displays
            if platform.system() == "Windows" and i < len(pnp_ids) and pnp_ids[i]:
                pnp_id_str = pnp_ids[i].upper()
                if any(x in pnp_id_str for x in ["SHP", "BOE", "LGD", "AUO", "SEC", "EDP"]):
                    logging.info(f"Skipping internal laptop display at index {i} ({pnp_id_str})")
                    continue

            # Default
            model = "Unknown"
            brand = "Unknown"

            # Try to read from VCP
            try:
                with monitor_obj:
                    caps = monitor_obj.get_vcp_capabilities()
                    model = caps.get('model', "Unknown")
            except:
                pass

            # If VCP failed, try EDID
            if model == "Unknown" and platform.system() == "Windows" and i < len(pnp_ids) and pnp_ids[i]:
                edid = read_edid(pnp_ids[i])
                if edid:
                    model = parse_edid(edid)

            # Determine Brand
            if platform.system() == "Windows":
                # First try to get brand from model prefix (more reliable)
                if model != "Unknown":
                    model_upper = model.upper()
                    logging.info(f"Trying to match model: {model_upper}")
                    for prefix, brand_name in MODEL_BRAND_MAP.items():
                        if model_upper.startswith(prefix):
                            brand = brand_name
                            logging.info(f"Found brand {brand} from model prefix {prefix}")
                            break
                    
                    # Special case for AOC monitors that might not match the prefix exactly
                    if brand == "Unknown" and ("G2" in model_upper or "G3" in model_upper or "G4" in model_upper):
                        brand = "AOC"
                        logging.info("Detected AOC monitor from G-series model number")
                
                # If brand is still unknown, try PNP ID
                if brand == "Unknown" and i < len(pnp_ids):
                    try:
                        if pnp_ids[i]:  # Check if PNP ID is not None
                            pnp_code = pnp_ids[i].split('\\')[1][:3].upper()
                            brand = PNP_IDS.get(pnp_code, "Unknown")
                            logging.info(f"Got brand {brand} from PNP code {pnp_code}")
                    except Exception as e:
                        logging.debug(f"Failed to get brand from PNP ID for monitor {i}: {e}")
                        pass

            # Inputs and connection type detection
            try:
                with monitor_obj:
                    caps = monitor_obj.get_vcp_capabilities()
                    inputs = caps.get('inputs', [])
                    input_names = [inp.name for inp in inputs]
                    
                    # Standard display inputs to check if not detected
                    standard_inputs = {
                        'DisplayPort': ["DP1", "DP2", "mDP1", "mDP2"],  # Including Mini DisplayPort
                        'HDMI': ["HDMI1", "HDMI2", "HDMI3", "HDMI4"],
                        'DVI': ["DVI1", "DVI2"],
                        'VGA': ["VGA1"],
                        'USB-C': ["USB-C1", "USB-C2", "TB1", "TB2"]  # Including Thunderbolt
                    }
                    
                    if not input_names:
                        # Try to detect available inputs from monitor capabilities
                        detected_inputs = []
                        for connection_type, inputs_list in standard_inputs.items():
                            for input_name in inputs_list:
                                try:
                                    # Try to query each potential input
                                    if hasattr(InputSource, input_name):
                                        detected_inputs.append(input_name)
                                except Exception:
                                    continue
                        
                        if detected_inputs:
                            input_names = detected_inputs
                        else:
                            # Fallback to common inputs
                            input_names = ["DP1", "HDMI1", "mDP1", "DVI1", "VGA1"]
                    
                    # Log connection capabilities
                    logging.info(f"Monitor {i} ({model}) supported inputs: {input_names}")
                    if 'mswhql' in caps:
                        logging.info(f"Monitor {i} WHQL certified: {caps['mswhql']}")
                    
                    # Log monitor resolution and refresh rate if available
                    if platform.system() == "Windows":
                        try:
                            c = wmi.WMI()
                            for monitor in c.Win32_DesktopMonitor():
                                if monitor.PNPDeviceID and i < len(pnp_ids) and pnp_ids[i] and monitor.PNPDeviceID in pnp_ids[i]:
                                    logging.info(f"Monitor {i} specs - Screen Height: {monitor.ScreenHeight}, "
                                               f"Screen Width: {monitor.ScreenWidth}")
                                    break
                        except Exception as e:
                            logging.debug(f"Could not get monitor specs: {e}")
                            
            except Exception as e:
                logging.warning(f"Could not get inputs for monitor {i}: {e}")
                # Comprehensive fallback input list
                input_names = ["DP1", "DP2", "mDP1", "HDMI1", "HDMI2", "DVI1", "VGA1", "USB-C1"]

            # Current input detection
            try:
                with monitor_obj:
                    current_input_obj = monitor_obj.get_input_source()
                    current_input = current_input_obj.name
                    logging.info(f"Monitor {i} current input: {current_input}")
            except Exception as e:
                logging.warning(f"Could not get current input for monitor {i}: {e}")
                current_input = "Unknown"
                
            # Additional connection information for USB-C/Thunderbolt displays
            if platform.system() == "Windows":
                try:
                    c = wmi.WMI()
                    # Check USB devices for potential USB-C display connections
                    usb_devices = c.Win32_USBHub()
                    for device in usb_devices:
                        if "display" in device.Description.lower() or "video" in device.Description.lower():
                            logging.info(f"Found USB display device: {device.Description}")
                except Exception as e:
                    logging.debug(f"Could not check USB display devices: {e}")

            all_data.append({
                "display_name": f"{brand} - {model}",
                "inputs": input_names,
                "id": i,
                "current_input": current_input
            })

        logging.info(f"All monitor data: {all_data}")
        return all_data

    def update_inputs(self, selected_monitor_name):
        for data in self.monitors_data:
            if data['display_name'] == selected_monitor_name:
                self.selected_monitor_data = data
                break
        
        self.input_menu.configure(values=self.selected_monitor_data['inputs'])
        if self.selected_monitor_data['inputs']:
            current_input = self.selected_monitor_data.get('current_input', "Unknown")
            if current_input in self.selected_monitor_data['inputs']:
                self.input_menu.set(current_input)
            else:
                self.input_menu.set(self.selected_monitor_data['inputs'][0])
        else:
            self.input_menu.set("No inputs found")

    def switch_input(self):
        new_input_str = self.input_menu.get()
        if new_input_str == "No inputs found" or not hasattr(self, 'selected_monitor_data'):
            self.status_label.configure(text="Cannot switch: No monitor or input selected.")
            return

        try:
            selected_monitor_id = self.selected_monitor_data['id']
            new_input = getattr(InputSource, new_input_str)
            with get_monitors()[selected_monitor_id] as monitor:
                monitor.set_input_source(new_input)

            self.status_label.configure(text=f"Successfully switched to {new_input_str}")

        except Exception as e:
            self.status_label.configure(text=f"Error switching input: {e}")
            logging.error(f"Failed to switch input: {e}")

    def get_current_screen(self):
        self.update_idletasks()
        x, y = self.winfo_x(), self.winfo_y()
        for screen in get_screen_info():
            if screen.x <= x < screen.x + screen.width and screen.y <= y < screen.y + screen.height:
                return screen
        return None

    def setup_global_hotkeys(self):
        """Setup global keyboard shortcuts"""
        try:
            # Register all shortcuts
            for shortcut, (monitor_id, input_source) in self.shortcuts.items():
                keyboard.add_hotkey(
                    shortcut,
                    lambda m=monitor_id, i=input_source: self.handle_global_hotkey(m, i)
                )
            
            # Add help shortcut
            keyboard.add_hotkey('ctrl+shift+h', self.show_shortcuts_help)
            
            logging.info("Global hotkeys registered successfully")
        except Exception as e:
            logging.error(f"Failed to register global hotkeys: {e}")
            self.status_label.configure(text="Warning: Could not register global hotkeys")

    def handle_global_hotkey(self, monitor_id, input_source):
        """Handle global hotkey press"""
        try:
            monitors = get_monitors()
            if monitor_id < len(monitors):
                with monitors[monitor_id] as monitor:
                    if hasattr(InputSource, input_source):
                        input_obj = getattr(InputSource, input_source)
                        monitor.set_input_source(input_obj)
                        self.status_label.configure(text=f"Switched monitor {monitor_id} to {input_source}")
                        logging.info(f"Hotkey: Switched monitor {monitor_id} to {input_source}")
                    else:
                        self.status_label.configure(text=f"Error: Invalid input source {input_source}")
            else:
                self.status_label.configure(text=f"Error: Monitor {monitor_id} not found")
        except Exception as e:
            self.status_label.configure(text=f"Error switching input: {e}")
            logging.error(f"Hotkey error: {e}")

    def load_shortcuts(self):
        """Load custom shortcuts from file"""
        try:
            if os.path.exists(self.shortcuts_file):
                with open(self.shortcuts_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Error loading shortcuts: {e}")
        return None

    def save_shortcuts(self):
        """Save custom shortcuts to file"""
        try:
            with open(self.shortcuts_file, 'w') as f:
                json.dump(self.shortcuts, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving shortcuts: {e}")
            self.status_label.configure(text="Error saving shortcuts")

    def load_favorites(self):
        """Load favorites from file"""
        try:
            if os.path.exists(self.favorites_file):
                with open(self.favorites_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Error loading favorites: {e}")
        return None

    def save_favorites(self):
        """Save favorites to file"""
        try:
            with open(self.favorites_file, 'w') as f:
                json.dump(self.favorites, f, indent=4)
            logging.info(f"Saved {len(self.favorites)} favorites")
        except Exception as e:
            logging.error(f"Error saving favorites: {e}")

    def load_settings(self):
        """Load theme and color settings from file"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Error loading settings: {e}")
        return None

    def save_settings(self):
        """Save theme settings to file"""
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f, indent=4)
            logging.info(f"Saved settings: theme={self.settings.get('theme')}")
        except Exception as e:
            logging.error(f"Error saving settings: {e}")

    def apply_theme(self):
        """Apply the current theme settings"""
        try:
            theme = self.settings.get("theme", "dark")
            
            if theme in AVAILABLE_THEMES:
                customtkinter.set_appearance_mode(theme)
            
            logging.info(f"Applied theme: {theme}")
        except Exception as e:
            logging.error(f"Error applying theme: {e}")

    def add_favorite(self, name, monitor_id, input_source):
        """Add a favorite combination"""
        try:
            if not name or not isinstance(name, str):
                return False
            monitor_id = int(monitor_id)
            if not isinstance(input_source, str):
                return False
            
            self.favorites[name] = (monitor_id, input_source)
            self.save_favorites()
            logging.info(f"Added favorite '{name}': Monitor {monitor_id} → {input_source}")
            return True
        except Exception as e:
            logging.error(f"Failed to add favorite: {e}")
            return False

    def remove_favorite(self, name):
        """Remove a favorite"""
        try:
            if name in self.favorites:
                del self.favorites[name]
                self.save_favorites()
                logging.info(f"Removed favorite '{name}'")
                return True
        except Exception as e:
            logging.error(f"Failed to remove favorite: {e}")
        return False

    def switch_to_favorite(self, name):
        """Switch to a saved favorite"""
        try:
            if name not in self.favorites:
                self.status_label.configure(text=f"Favorite '{name}' not found")
                return False
            
            monitor_id, input_source = self.favorites[name]
            monitors = get_monitors()
            
            if monitor_id >= len(monitors):
                self.status_label.configure(text=f"Monitor {monitor_id} not found")
                return False
            
            with monitors[monitor_id] as monitor:
                if hasattr(InputSource, input_source):
                    input_obj = getattr(InputSource, input_source)
                    monitor.set_input_source(input_obj)
                    self.status_label.configure(text=f"Switched to favorite '{name}'")
                    logging.info(f"Switched to favorite '{name}': Monitor {monitor_id} → {input_source}")
                    return True
                else:
                    self.status_label.configure(text=f"Invalid input source: {input_source}")
                    return False
        except Exception as e:
            self.status_label.configure(text=f"Error switching to favorite: {e}")
            logging.error(f"Error switching to favorite '{name}': {e}")
            return False

    def add_shortcut(self, shortcut_key, monitor_id, input_source):
        """Add a new shortcut programmatically, persist it, and register hotkeys.

        Returns True on success, False on failure.
        """
        try:
            # Basic validation
            if not isinstance(shortcut_key, str) or not shortcut_key:
                logging.error("Invalid shortcut key provided")
                return False

            monitor_id = int(monitor_id)
            if not isinstance(input_source, str) or not input_source:
                logging.error("Invalid input source provided")
                return False

            # Save to in-memory dict
            self.shortcuts[shortcut_key] = (monitor_id, input_source)

            # Persist and refresh hotkeys
            self.save_shortcuts()
            try:
                # Clear existing hotkeys and re-register
                keyboard.clear_all_hotkeys()
            except Exception:
                pass
            self.setup_global_hotkeys()

            logging.info(f"Added shortcut {shortcut_key} -> Monitor {monitor_id} : {input_source}")
            return True
        except Exception as e:
            logging.error(f"Failed to add shortcut: {e}")
            return False

    def switch_to_favorite(self, name):
        """Switch to a saved favorite"""
        try:
            if name not in self.favorites:
                self.status_label.configure(text=f"Favorite '{name}' not found")
                return False
            
            monitor_id, input_source = self.favorites[name]
            monitors = get_monitors()
            
            if monitor_id >= len(monitors):
                self.status_label.configure(text=f"Monitor {monitor_id} not found")
                return False
            
            with monitors[monitor_id] as monitor:
                if hasattr(InputSource, input_source):
                    input_obj = getattr(InputSource, input_source)
                    monitor.set_input_source(input_obj)
                    self.status_label.configure(text=f"Switched to favorite '{name}'")
                    logging.info(f"Switched to favorite '{name}': Monitor {monitor_id} → {input_source}")
                    return True
                else:
                    self.status_label.configure(text=f"Invalid input source: {input_source}")
                    return False
        except Exception as e:
            self.status_label.configure(text=f"Error switching to favorite: {e}")
            logging.error(f"Error switching to favorite '{name}': {e}")
            return False

    def refresh_favorites_buttons(self):
        """Rebuild favorites buttons in the main window"""
        # Clear existing buttons
        for widget in self.favorites_frame.winfo_children():
            widget.destroy()
        
        if not self.favorites:
            no_fav_label = customtkinter.CTkLabel(self.favorites_frame, text="No favorites yet. Click 'Manage Favorites' to add one.", text_color="gray")
            no_fav_label.pack(pady=5)
            return
        
        # Create a horizontal scrollable/wrappable layout for favorites
        for fav_name, (monitor_id, input_source) in list(self.favorites.items()):
            fav_btn = customtkinter.CTkButton(
                self.favorites_frame,
                text=fav_name,
                command=lambda n=fav_name: self.switch_to_favorite(n),
                width=120,
                height=28
            )
            fav_btn.pack(side="left", padx=3, pady=2)

    def show_theme_settings(self):
        """Show dialog to change application theme"""
        theme_window = customtkinter.CTkToplevel(self)
        theme_window.title("Theme Settings")
        theme_window.geometry("300x200")
        
        # Make window modal
        theme_window.transient(self)
        theme_window.grab_set()
        
        # Create main frame
        frame = customtkinter.CTkFrame(theme_window)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        title = customtkinter.CTkLabel(frame, text="Application Theme", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 20))
        
        current_theme = self.settings.get("theme", "dark")
        theme_var = customtkinter.StringVar(value=current_theme)
        
        # Theme options
        for theme in AVAILABLE_THEMES:
            theme_radio = customtkinter.CTkRadioButton(
                frame,
                text=theme.capitalize(),
                variable=theme_var,
                value=theme
            )
            theme_radio.pack(anchor="w", padx=20, pady=8)
        
        # Buttons
        button_frame = customtkinter.CTkFrame(frame)
        button_frame.pack(fill="x", pady=(20, 0))
        
        def apply_settings():
            self.settings["theme"] = theme_var.get()
            self.save_settings()
            self.apply_theme()
            self.status_label.configure(text="Theme changed. Please restart for full effect.")
            theme_window.destroy()
        
        apply_btn = customtkinter.CTkButton(button_frame, text="Apply", command=apply_settings)
        apply_btn.pack(side="left", padx=(0, 10), expand=True, fill="x")
        
        cancel_btn = customtkinter.CTkButton(button_frame, text="Cancel", command=theme_window.destroy)
        cancel_btn.pack(side="right", padx=(10, 0), expand=True, fill="x")

    def show_manage_favorites(self):
        """Show dialog to manage favorites"""
        manage_window = customtkinter.CTkToplevel(self)
        manage_window.title("Manage Favorites")
        manage_window.geometry("450x500")
        
        # Make window modal
        manage_window.transient(self)
        manage_window.grab_set()
        
        # Create scrollable frame
        frame = customtkinter.CTkScrollableFrame(manage_window)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Add title
        title = customtkinter.CTkLabel(frame, text="Manage Favorite Setups", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 20))
        
        # Instructions
        instructions = "Save your most-used monitor/input combinations for quick switching."
        help_label = customtkinter.CTkLabel(frame, text=instructions, wraplength=350)
        help_label.pack(pady=(0, 20))

        # Favorites list frame
        favorites_list_frame = customtkinter.CTkFrame(frame)
        favorites_list_frame.pack(fill="x", padx=5, pady=5)
        
        def update_favorites_list():
            # Clear existing
            for widget in favorites_list_frame.winfo_children():
                widget.destroy()
            
            # Add header
            header = customtkinter.CTkLabel(favorites_list_frame, text="Current Favorites:", font=("Arial", 12, "bold"))
            header.pack(anchor="w", pady=(0, 10))
            
            if not self.favorites:
                empty_label = customtkinter.CTkLabel(favorites_list_frame, text="No favorites saved yet.")
                empty_label.pack(anchor="w")
                return
            
            # List each favorite
            for fav_name, (monitor_id, input_source) in self.favorites.items():
                fav_frame = customtkinter.CTkFrame(favorites_list_frame)
                fav_frame.pack(fill="x", pady=2)
                
                # Find monitor display name
                try:
                    mon = next((m for m in self.monitors_data if m.get('id') == monitor_id), None)
                    display_name = mon.get('display_name', f"Monitor {monitor_id}") if mon else f"Monitor {monitor_id}"
                except Exception:
                    display_name = f"Monitor {monitor_id}"
                
                label_text = f"{fav_name}: {display_name} → {input_source}"
                label = customtkinter.CTkLabel(fav_frame, text=label_text)
                label.pack(side="left", padx=5)
                
                delete_btn = customtkinter.CTkButton(
                    fav_frame, text="Delete", width=60,
                    command=lambda n=fav_name: delete_favorite(n)
                )
                delete_btn.pack(side="right", padx=5)
        
        def delete_favorite(name):
            self.remove_favorite(name)
            update_favorites_list()
            self.refresh_favorites_buttons()
        
        # Add new favorite section
        add_frame = customtkinter.CTkFrame(frame)
        add_frame.pack(fill="x", padx=5, pady=(20, 5))
        
        add_label = customtkinter.CTkLabel(add_frame, text="Add New Favorite", font=("Arial", 12, "bold"))
        add_label.pack(anchor="w", pady=(0, 10))
        
        # Favorite name input
        name_label = customtkinter.CTkLabel(add_frame, text="Favorite Name:")
        name_label.pack(anchor="w", pady=(5, 0))
        name_var = customtkinter.StringVar(value="My Setup")
        name_entry = customtkinter.CTkEntry(add_frame, textvariable=name_var)
        name_entry.pack(fill="x", pady=5)
        
        # Monitor selection
        mon_label = customtkinter.CTkLabel(add_frame, text="Monitor:")
        mon_label.pack(anchor="w", pady=(5, 0))
        
        try:
            monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else []
        except Exception:
            monitors_list = []
        
        mon_choices = [f"{m.get('id')}: {m.get('display_name')}" for m in monitors_list]
        if not mon_choices:
            mon_choices = ["0"]
        
        mon_var = customtkinter.StringVar(value=mon_choices[0])
        mon_menu = customtkinter.CTkOptionMenu(add_frame, variable=mon_var, values=mon_choices)
        mon_menu.pack(fill="x", pady=5)
        
        # Input selection (dynamic based on monitor)
        input_label = customtkinter.CTkLabel(add_frame, text="Input:")
        input_label.pack(anchor="w", pady=(5, 0))
        
        initial_inputs = []
        if monitors_list:
            try:
                initial_inputs = monitors_list[0].get('inputs', []) or []
            except Exception:
                pass
        if not initial_inputs:
            initial_inputs = ["HDMI1", "DP1", "DP2"]
        
        input_var = customtkinter.StringVar(value=initial_inputs[0])
        input_menu = customtkinter.CTkOptionMenu(add_frame, variable=input_var, values=initial_inputs)
        input_menu.pack(fill="x", pady=5)
        
        def update_input_options(*args):
            sel = mon_var.get()
            try:
                if ':' in sel:
                    sel_id = int(sel.split(':', 1)[0].strip())
                else:
                    sel_id = int(sel)
            except Exception:
                sel_id = None
            
            inputs_for_sel = []
            if sel_id is not None and monitors_list:
                for mon in monitors_list:
                    if mon.get('id') == sel_id:
                        inputs_for_sel = mon.get('inputs', []) or []
                        break
            
            if not inputs_for_sel:
                inputs_for_sel = ["DP1", "DP2", "mDP1", "HDMI1", "HDMI2", "DVI1", "VGA1", "USB-C1"]
            
            try:
                input_menu.configure(values=inputs_for_sel)
                input_var.set(inputs_for_sel[0])
            except Exception:
                pass
        
        try:
            mon_var.trace_add('write', update_input_options)
        except Exception:
            mon_var.trace('w', update_input_options)
        
        def add_fav():
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Error", "Please enter a favorite name")
                return
            
            sel = mon_var.get()
            try:
                if ':' in sel:
                    monitor_id = int(sel.split(':', 1)[0].strip())
                else:
                    monitor_id = int(sel)
            except ValueError:
                messagebox.showerror("Error", "Invalid monitor selection")
                return
            
            input_source = input_var.get()
            
            if self.add_favorite(name, monitor_id, input_source):
                update_favorites_list()
                self.refresh_favorites_buttons()
                name_var.set("My Setup")
                messagebox.showinfo("Success", f"Favorite '{name}' added!")
            else:
                messagebox.showerror("Error", "Failed to add favorite")
        
        add_btn = customtkinter.CTkButton(add_frame, text="Add Favorite", command=add_fav)
        add_btn.pack(pady=10)
        
        # Initialize list
        update_favorites_list()

    def show_shortcuts_editor(self):
        """Show the shortcuts editor window"""
        editor_window = customtkinter.CTkToplevel(self)
        editor_window.title("Customize Shortcuts")
        editor_window.geometry("500x600")
        
        # Make window modal
        editor_window.transient(self)
        editor_window.grab_set()
        
        # Create scrollable frame
        frame = customtkinter.CTkScrollableFrame(editor_window)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Add title
        title = customtkinter.CTkLabel(frame, text="Customize Keyboard Shortcuts", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 20))
        
        # Instructions
        instructions = (
            "Click 'Add New' to create a new shortcut\n"
            "Click 'Edit' to modify existing shortcuts\n"
            "Press the desired keys when recording a shortcut\n"
            "Available modifiers: ctrl, alt, shift"
        )
        help_label = customtkinter.CTkLabel(frame, text=instructions)
        help_label.pack(pady=(0, 20))

        # Shortcuts list frame
        shortcuts_frame = customtkinter.CTkFrame(frame)
        shortcuts_frame.pack(fill="x", padx=5, pady=5)
        
        def update_shortcuts_list():
            # Clear existing shortcuts
            for widget in shortcuts_frame.winfo_children():
                widget.destroy()
                
            # Add header
            header = customtkinter.CTkLabel(shortcuts_frame, text="Current Shortcuts:", font=("Arial", 12, "bold"))
            header.pack(anchor="w", pady=(0, 10))
            
            # Add each shortcut
            # Only show shortcuts that target currently-detected monitors
            try:
                monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else self.get_all_monitor_data()
            except Exception:
                monitors_list = []

            shown = 0
            for shortcut, (monitor_id, input_source) in self.shortcuts.items():
                # find monitor by id
                mon = next((m for m in monitors_list if m.get('id') == monitor_id), None)
                if not mon:
                    # skip shortcuts for monitors that are not currently present
                    continue

                shown += 1
                shortcut_frame = customtkinter.CTkFrame(shortcuts_frame)
                shortcut_frame.pack(fill="x", pady=2)

                display_name = mon.get('display_name', f"Monitor {monitor_id}")
                label = customtkinter.CTkLabel(shortcut_frame, 
                    text=f"{shortcut}: {display_name} → {input_source}")
                label.pack(side="left", padx=5)

                edit_btn = customtkinter.CTkButton(shortcut_frame, text="Edit", 
                    width=60, command=lambda s=shortcut: edit_shortcut(s))
                edit_btn.pack(side="right", padx=5)

                delete_btn = customtkinter.CTkButton(shortcut_frame, text="Delete", 
                    width=60, command=lambda s=shortcut: delete_shortcut(s))
                delete_btn.pack(side="right", padx=5)

            if shown == 0:
                notice = customtkinter.CTkLabel(shortcuts_frame, text="No shortcuts for currently connected monitors.")
                notice.pack(anchor="w", pady=(5, 0))

        def record_shortcut(callback):
            dialog = customtkinter.CTkToplevel(editor_window)
            dialog.title("Record Shortcut")
            dialog.geometry("300x150")
            dialog.transient(editor_window)
            dialog.grab_set()
            
            label = customtkinter.CTkLabel(dialog, text="Press the desired key combination...")
            label.pack(pady=20)
            
            recorded_keys = []
            
            def on_key(event):
                if event.name not in recorded_keys and event.name not in ['ctrl', 'alt', 'shift']:
                    recorded_keys.extend(k for k in ['ctrl', 'alt', 'shift'] if keyboard.is_pressed(k))
                    recorded_keys.append(event.name)
                    shortcut = '+'.join(recorded_keys)
                    label.configure(text=f"Recorded: {shortcut}\nPress Enter to confirm or Esc to cancel")
                    
                    if event.name == 'enter':
                        dialog.destroy()
                        callback('+'.join(recorded_keys[:-1]))  # Remove 'enter' from the shortcut
                    elif event.name == 'esc':
                        dialog.destroy()
            
            keyboard.on_press(on_key)
            
        def add_new_shortcut():
            def on_shortcut(shortcut):
                if shortcut:
                    # Show monitor and input selection dialog
                    select_dialog = customtkinter.CTkToplevel(editor_window)
                    select_dialog.title("Configure Shortcut")
                    select_dialog.geometry("380x240")
                    select_dialog.transient(editor_window)
                    select_dialog.grab_set()

                    # Monitor selection (populate from detected monitors if available)
                    monitor_label = customtkinter.CTkLabel(select_dialog, text="Select Monitor:")
                    monitor_label.pack(pady=(10, 5))

                    # Get current monitors info (use existing data if available)
                    try:
                        monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else self.get_all_monitor_data()
                    except Exception:
                        monitors_list = []

                    monitor_choices = []
                    for m in monitors_list:
                        # format: "0: AOC - 27G4"
                        monitor_choices.append(f"{m.get('id')}: {m.get('display_name')}")

                    # Fallback to a simple numeric choice if no monitors detected yet
                    if not monitor_choices:
                        monitor_choices = ["0"]

                    monitor_var = customtkinter.StringVar(value=monitor_choices[0])
                    monitor_menu = customtkinter.CTkOptionMenu(select_dialog, variable=monitor_var, values=monitor_choices)
                    monitor_menu.pack(pady=5)

                    # Input selection (will be populated based on selected monitor)
                    input_label = customtkinter.CTkLabel(select_dialog, text="Select Input:")
                    input_label.pack(pady=(10, 5))
                    input_var = customtkinter.StringVar(value="")
                    # start with inputs from the first monitor choice if available
                    initial_inputs = []
                    if monitors_list:
                        try:
                            initial_inputs = monitors_list[0].get('inputs', []) or []
                        except Exception:
                            initial_inputs = []
                    if not initial_inputs:
                        initial_inputs = ["HDMI1", "DP1", "DP2"]

                    input_menu = customtkinter.CTkOptionMenu(select_dialog, variable=input_var, values=initial_inputs)
                    input_menu.pack(pady=5)

                    def save():
                        try:
                            # monitor_var holds a selection like "0: AOC - 27G4" or a plain number fallback
                            sel = monitor_var.get()
                            if isinstance(sel, str) and ':' in sel:
                                monitor_id = int(sel.split(':', 1)[0].strip())
                            else:
                                monitor_id = int(sel)

                            input_source = input_var.get()
                            ok = self.add_shortcut(shortcut, monitor_id, input_source)
                            if ok:
                                try:
                                    update_shortcuts_list()
                                except Exception:
                                    pass
                                select_dialog.destroy()
                            else:
                                messagebox.showerror("Error", "Failed to save shortcut")
                        except ValueError:
                            messagebox.showerror("Error", "Invalid monitor number")

                    save_btn = customtkinter.CTkButton(select_dialog, text="Save", command=save)
                    save_btn.pack(pady=12)

                    # update input menu when monitor selection changes
                    def update_input_options(*args):
                        sel = monitor_var.get()
                        try:
                            if isinstance(sel, str) and ':' in sel:
                                sel_id = int(sel.split(':', 1)[0].strip())
                            else:
                                sel_id = int(sel)
                        except Exception:
                            sel_id = None

                        inputs_for_sel = []
                        if sel_id is not None and monitors_list:
                            for mon in monitors_list:
                                if mon.get('id') == sel_id:
                                    inputs_for_sel = mon.get('inputs', []) or []
                                    break

                        if not inputs_for_sel:
                            # fallback comprehensive list
                            inputs_for_sel = ["DP1", "DP2", "mDP1", "HDMI1", "HDMI2", "DVI1", "VGA1", "USB-C1"]

                        # update option menu values
                        try:
                            input_menu.configure(values=inputs_for_sel)
                            input_var.set(inputs_for_sel[0])
                        except Exception:
                            pass

                    # attach trace to update inputs when monitor selection changes
                    try:
                        monitor_var.trace_add('write', update_input_options)
                    except Exception:
                        monitor_var.trace('w', update_input_options)

                    # initialize inputs
                    update_input_options()
            
            record_shortcut(on_shortcut)
            
        def edit_shortcut(shortcut):
            def on_new_shortcut(new_shortcut):
                if new_shortcut and new_shortcut != shortcut:
                    value = self.shortcuts.pop(shortcut)
                    self.shortcuts[new_shortcut] = value
                    self.save_shortcuts()
                    self.setup_global_hotkeys()  # Refresh hotkeys
                    update_shortcuts_list()
            
            record_shortcut(on_new_shortcut)
            
        def delete_shortcut(shortcut):
            self.shortcuts.pop(shortcut)
            self.save_shortcuts()
            self.setup_global_hotkeys()  # Refresh hotkeys
            update_shortcuts_list()
        
        # Add New Shortcut button
        add_button = customtkinter.CTkButton(frame, text="Add New Shortcut", command=add_new_shortcut)
        add_button.pack(pady=20)
        
        # Reset to Defaults button
        def reset_defaults():
            self.shortcuts = self.default_shortcuts.copy()
            self.save_shortcuts()
            self.setup_global_hotkeys()
            update_shortcuts_list()
            
        reset_button = customtkinter.CTkButton(frame, text="Reset to Defaults", command=reset_defaults)
        reset_button.pack(pady=10)
        
        # Initialize the shortcuts list
        update_shortcuts_list()

    def show_shortcuts_help(self):
        """Show a help window with all available shortcuts"""
        help_window = customtkinter.CTkToplevel(self)
        help_window.title("Keyboard Shortcuts")
        help_window.geometry("400x300")
        
        # Make window modal
        help_window.transient(self)
        help_window.grab_set()
        
        # Create scrollable frame
        frame = customtkinter.CTkScrollableFrame(help_window)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Add title
        title = customtkinter.CTkLabel(frame, text="Available Shortcuts", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 10))
        
        # Add shortcuts list
        for shortcut, (monitor_id, input_source) in self.shortcuts.items():
            text = f"{shortcut}: Switch Monitor {monitor_id} to {input_source}"
            label = customtkinter.CTkLabel(frame, text=text)
            label.pack(anchor="w", pady=2)
            
        # Add help shortcut
        help_shortcut = customtkinter.CTkLabel(frame, text="\nctrl+shift+h: Show this help window")
        help_shortcut.pack(anchor="w", pady=(10, 2))
            
        # Add customize button
        customize_btn = customtkinter.CTkButton(frame, text="Customize Shortcuts", 
            command=lambda: [help_window.destroy(), self.show_shortcuts_editor()])
        customize_btn.pack(pady=(20, 0))

def cli_switch_input(monitor_index, input_name):
    """Switch input via command line interface"""
    try:
        monitors = get_monitors()
        if not monitors:
            logging.error("No monitors found")
            print("Error: No monitors found")
            return False

        if monitor_index >= len(monitors):
            logging.error(f"Monitor index {monitor_index} is out of range. Found {len(monitors)} monitors.")
            print(f"Error: Monitor index {monitor_index} is out of range. Found {len(monitors)} monitors.")
            return False

        with monitors[monitor_index] as monitor:
            try:
                # Verify input exists
                if not hasattr(InputSource, input_name):
                    logging.error(f"Invalid input source: {input_name}")
                    print(f"Error: Invalid input source: {input_name}")
                    print("Available inputs: " + ", ".join([x for x in dir(InputSource) if not x.startswith('_')]))
                    return False

                new_input = getattr(InputSource, input_name)
                monitor.set_input_source(new_input)
                logging.info(f"Successfully switched monitor {monitor_index} to {input_name}")
                print(f"Successfully switched monitor {monitor_index} to {input_name}")
                return True

            except Exception as e:
                logging.error(f"Failed to switch input: {e}")
                print(f"Error: Failed to switch input: {e}")
                return False

    except Exception as e:
        logging.error(f"Failed to access monitors: {e}")
        print(f"Error: Failed to access monitors: {e}")
        return False

def cli_list_monitors():
    """List all available monitors and their inputs"""
    try:
        # Create a temporary App instance to use its monitor detection
        app = App()
        monitors_data = app.get_all_monitor_data()
        app.destroy()

        if not monitors_data:
            print("No monitors found")
            return

        print("\nAvailable Monitors:")
        print("-" * 50)
        for monitor in monitors_data:
            print(f"Monitor {monitor['id']}: {monitor['display_name']}")
            print(f"Current Input: {monitor['current_input']}")
            print(f"Available Inputs: {', '.join(monitor['inputs'])}")
            print("-" * 50)

    except Exception as e:
        logging.error(f"Failed to list monitors: {e}")
        print(f"Error: Failed to list monitors: {e}")

if __name__ == "__main__":
    try:
        import argparse
        parser = argparse.ArgumentParser(description='Monitor Input Switcher')
        
        # Command-line arguments
        parser.add_argument('--cli', action='store_true', help='Run in CLI mode')
        parser.add_argument('--list', action='store_true', help='List all monitors and their inputs')
        parser.add_argument('--monitor', type=int, help='Monitor index to control')
        parser.add_argument('--input', type=str, help='Input source to switch to (e.g., HDMI1, DP1)')
        
        args = parser.parse_args()

        # CLI Mode
        if args.cli or args.list or args.monitor is not None or args.input is not None:
            if args.list:
                cli_list_monitors()
            elif args.monitor is not None and args.input is not None:
                cli_switch_input(args.monitor, args.input)
            else:
                print("Error: For CLI mode, use either --list to list monitors,")
                print("or both --monitor and --input to switch inputs.")
                print("\nExample usage:")
                print("  monitor_manager.exe --list")
                print("  monitor_manager.exe --monitor 0 --input HDMI1")
        # GUI Mode
        else:
            app = App()
            app.mainloop()
    except Exception as e:
        logging.critical(f"Unhandled exception: {e}", exc_info=True)
