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
import winreg
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw

# Available themes for customtkinter
AVAILABLE_THEMES = ["dark", "light"]

# Import WMI only on Windows
if platform.system() == 'Windows':
    import wmi
    import pythoncom

def get_user_config_dir():
    """Return a writable config directory for storing user data (shortcuts, settings)."""
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
        return os.path.abspath('.')

# Set up logging in user's config directory
config_dir = get_user_config_dir()
try:
    os.makedirs(config_dir, exist_ok=True)
except Exception:
    pass
log_file = os.path.join(config_dir, 'monitor_manager.log')
logging.basicConfig(filename=log_file, level=logging.INFO, 
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
    "PA": "ASUS", "PG": "ASUS", "VG": "ASUS", "MG": "ASUS", "ROG": "ASUS", 
    "TUF": "ASUS", "XG": "ASUS", "BE": "ASUS", "VP": "ASUS",
    "AW": "Alienware", "U": "Dell", "P": "Dell", "S": "Dell", "E": "Dell",
    "LG": "LG", "MP": "LG", "GP": "LG", "OLED": "LG", "GL": "LG", 
    "GN": "LG", "UK": "LG", "UM": "LG",
    "C": "Samsung", "G": "Samsung", "ODYSSEY": "Samsung", "S": "Samsung",
    "U": "Samsung", "F": "Samsung", "LS": "Samsung",
    "27G": "AOC", "24G": "AOC", "22": "AOC", "Q27": "AOC", "CQ": "AOC",
    "C24": "AOC", "C27": "AOC", "C32": "AOC", "AG": "AOC", "AGON": "AOC",
    "VX": "ViewSonic", "XG": "ViewSonic", "VA": "ViewSonic", "VP": "ViewSonic",
    "XL": "BenQ", "EX": "BenQ", "PD": "BenQ", "EW": "BenQ", "ZOWIE": "BenQ",
    "XV": "Acer", "XF": "Acer", "KG": "Acer", "CB": "Acer", "XB": "Acer",
    "NITRO": "Acer", "PREDATOR": "Acer",
    "MAG": "MSI", "MPG": "MSI", "OPTIX": "MSI", "MEG": "MSI",
    "FI": "Gigabyte", "M": "Gigabyte", "G27": "Gigabyte", "AORUS": "Gigabyte",
    "OMEN": "HP", "X27": "HP", "Z27": "HP", "PAVILION": "HP",
    "BDM": "Philips", "PHL": "Philips", "PHI": "Philips"
}

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class App(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        self.title("Monitor Input Switcher")
        self.geometry("520x540")
        self.resizable(True, True)  # Allow window resizing
        
        try:
            self.iconbitmap(resource_path('monitor_manager_icon.ico'))
        except:
            pass
        
        # System tray setup
        self.tray_icon = None
        self.is_quitting = False
        
        # Override window close behavior and minimize behavior
        self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        self.bind("<Unmap>", self.on_minimize)

        # Default shortcut configuration
        self.default_shortcuts = {
            'ctrl+shift+1': (0, 'HDMI1'),
            'ctrl+shift+2': (0, 'DP1'),
            'ctrl+shift+3': (1, 'HDMI1'),
            'ctrl+shift+4': (1, 'DP1'),
        }
        
        # Configuration paths
        config_dir = get_user_config_dir()
        try:
            os.makedirs(config_dir, exist_ok=True)
        except Exception:
            pass

        self.shortcuts_file = os.path.join(config_dir, 'custom_shortcuts.json')
        self.favorites_file = os.path.join(config_dir, 'favorites.json')
        self.settings_file = os.path.join(config_dir, 'settings.json')

        # Migrate old shortcuts file if exists
        old_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'custom_shortcuts.json')
        try:
            if os.path.exists(old_path) and not os.path.exists(self.shortcuts_file):
                shutil.copy2(old_path, self.shortcuts_file)
                logging.info(f"Migrated shortcuts file from {old_path} to {self.shortcuts_file}")
        except Exception as e:
            logging.debug(f"Could not migrate old shortcuts file: {e}")
            
        self.shortcuts = self.load_shortcuts() or self.default_shortcuts
        self.favorites = self.load_favorites() or {}
        self.settings = self.load_settings() or {"theme": "light"}
        self.apply_theme()
        
        self.setup_global_hotkeys()

        # ===== MAIN CONTAINER =====
        main_container = customtkinter.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=15, pady=15)

        # ===== HEADER =====
        header = customtkinter.CTkFrame(main_container, height=50)
        header.pack(fill="x", pady=(0, 12))
        header.pack_propagate(False)
        
        title_label = customtkinter.CTkLabel(
            header, 
            text="🖥️ Monitor Input Switcher", 
            font=("Arial", 20, "bold")
        )
        title_label.pack(side="left", padx=10, pady=10)

        # Theme and Settings buttons in header
        btn_frame = customtkinter.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right", padx=10)
        
        self.theme_button = customtkinter.CTkButton(
            btn_frame, 
            text="🎨", 
            command=self.show_theme_settings,
            width=35,
            height=35,
            font=("Arial", 16)
        )
        self.theme_button.pack(side="right", padx=2)
        
        self.shortcuts_button = customtkinter.CTkButton(
            btn_frame, 
            text="⌨", 
            command=self.show_shortcuts_editor,
            state="disabled",
            width=35,
            height=35,
            font=("Arial", 16)
        )
        self.shortcuts_button.pack(side="right", padx=2)

        # Add Settings button beside the keyboard shortcut button
        # self.settings_button = customtkinter.CTkButton(
        #     btn_frame,
        #     text="⚙",  # Gear icon for settings
        #     command=self.show_settings,
        #     width=35,
        #     height=35,
        #     font=("Arial", 16)
        #     )
        # self.settings_button.pack(side="right", padx=2)

        # ===== MONITOR SELECTION CARD =====
        monitor_card = customtkinter.CTkFrame(main_container)
        monitor_card.pack(fill="x", pady=(0, 10))
        
        monitor_header = customtkinter.CTkFrame(monitor_card, fg_color="transparent")
        monitor_header.pack(fill="x", padx=12, pady=(12, 8))
        
        self.monitor_label = customtkinter.CTkLabel(
            monitor_header, 
            text="📺 Select Monitor", 
            font=("Arial", 13, "bold")
        )
        self.monitor_label.pack(side="left")
        
        self.refresh_button = customtkinter.CTkButton(
            monitor_header, 
            text="Refresh🔄",
            command=self.refresh_monitors,
            width=30,
            height=28,
            font=("Arial", 14)
        )
        self.refresh_button.pack(side="right")

        self.monitor_menu = customtkinter.CTkOptionMenu(
            monitor_card, 
            values=["Loading..."],
            command=self.update_inputs,
            height=32,
            font=("Arial", 12)
        )
        self.monitor_menu.set("Loading...")
        self.monitor_menu.pack(fill="x", padx=12, pady=(0, 12))

        # ===== INPUT SOURCE CARD =====
        input_card = customtkinter.CTkFrame(main_container)
        input_card.pack(fill="x", pady=(0, 10))
        
        self.input_label = customtkinter.CTkLabel(
            input_card, 
            text="🔌 Select Input Source", 
            font=("Arial", 13, "bold")
        )
        self.input_label.pack(anchor="w", padx=12, pady=(12, 8))

        self.input_menu = customtkinter.CTkOptionMenu(
            input_card, 
            values=["Loading..."],
            height=32,
            font=("Arial", 12)
        )
        self.input_menu.set("Loading...")
        self.input_menu.pack(fill="x", padx=12, pady=(0, 12))

        # ===== SWITCH BUTTON =====
        self.switch_button = customtkinter.CTkButton(
            main_container,
            text="⚡ Switch Input",
            command=self.switch_input,
            height=42,
            font=("Arial", 14, "bold"),
            fg_color=("#2B7A0B", "#5FB041"),
            hover_color=("#246A09", "#52A038")
        )
        self.switch_button.pack(fill="x", pady=(0, 10))

        # Progress bar (hidden by default)
        self.progress_bar = customtkinter.CTkProgressBar(main_container, mode='indeterminate')

        # ===== FAVORITES SECTION =====
        favorites_card = customtkinter.CTkFrame(main_container)
        # Don't expand by default; will grow when favorites are added
        favorites_card.pack(fill="x", expand=False, pady=(0, 10))
        
        fav_header = customtkinter.CTkFrame(favorites_card, fg_color="transparent")
        fav_header.pack(fill="x", padx=12, pady=(12, 8))
        
        self.favorites_label = customtkinter.CTkLabel(
            fav_header, 
            text="⭐ Quick Favorites", 
            font=("Arial", 13, "bold")
        )
        self.favorites_label.pack(side="left")

        self.manage_favorites_btn = customtkinter.CTkButton(
            fav_header,
            text="+ Manage",
            command=self.show_manage_favorites,
            state="disabled",
            width=80,
            height=26,
            font=("Arial", 11)
        )
        self.manage_favorites_btn.pack(side="right")

        # Favorites container - regular frame without scrolling, minimal height
        self.favorites_scroll = customtkinter.CTkFrame(
            favorites_card,
            fg_color="transparent",
            height=40
        )
        self.favorites_scroll.pack(fill="x", expand=False, padx=12, pady=(0, 12))
        self.favorites_scroll.pack_propagate(False)

        # ===== STATUS BAR =====
        status_frame = customtkinter.CTkFrame(main_container, height=40)
        status_frame.pack(fill="x", pady=(0, 0))
        status_frame.pack_propagate(False)
        
        self.status_label = customtkinter.CTkLabel(
            status_frame,
            text="Ready",
            font=("Arial", 11),
            wraplength=480
        )
        self.status_label.pack(pady=8)

        # ===== FOOTER =====
        footer = customtkinter.CTkLabel(
            main_container,
            text="By: LuqmanHakimAmiruddin@PDC",
            font=("Arial", 9),
            text_color="gray"
        )
        footer.pack(pady=(5, 0))

        # Start initial refresh
        self.after(100, self.refresh_monitors)

    def refresh_monitors(self):
        self.status_label.configure(text="🔍 Detecting monitors...")
        self.progress_bar.pack(pady=(0, 10), fill="x")
        self.progress_bar.start()

        self.switch_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self.monitor_menu.configure(values=["Loading..."])
        self.monitor_menu.set("Loading...")
        self.input_menu.configure(values=["Loading..."])
        self.input_menu.set("Loading...")

        thread = threading.Thread(target=self.load_monitor_data_thread, daemon=True)
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
            self.status_label.configure(text="✅ Ready to switch inputs")
            self.shortcuts_button.configure(state="normal")
            self.manage_favorites_btn.configure(state="normal")
            self.refresh_favorites_buttons()
        else:
            self.monitor_menu.set("No monitors detected")
            self.input_menu.configure(values=[])
            self.input_menu.set("")
            self.status_label.configure(text="❌ No monitors found. Check connections and refresh.")
            self.shortcuts_button.configure(state="disabled")
            self.manage_favorites_btn.configure(state="disabled")

        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.switch_button.configure(state="normal")
        self.refresh_button.configure(state="normal")

    def get_all_monitor_data(self):
        """Get all monitor data - keeping original implementation"""
        all_data = []

        try:
            monitors = get_monitors()
            logging.info(f"Found {len(monitors)} monitors.")
            
            if platform.system() == "Windows":
                try:
                    c = wmi.WMI()
                    video_controllers = c.Win32_VideoController()
                    for controller in video_controllers:
                        logging.info(f"Display adapter: {controller.Name}, Status: {controller.Status}")
                except Exception as e:
                    logging.warning(f"Could not get display adapter info: {e}")
                    
        except Exception as e:
            logging.error(f"Could not get monitors: {e}")
            return []

        pnp_ids = []
        if platform.system() == "Windows":
            try:
                c = wmi.WMI()
                wmi_monitors = c.Win32_DesktopMonitor()
                for monitor in wmi_monitors:
                    pnp_ids.append(getattr(monitor, 'PNPDeviceID', None))
                logging.info(f"WMI PnP IDs: {pnp_ids}")
            except Exception as e:
                logging.error(f"Failed to get device information from WMI: {e}")

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
            if platform.system() == "Windows" and i < len(pnp_ids) and pnp_ids[i]:
                pnp_id_str = pnp_ids[i].upper()
                if any(x in pnp_id_str for x in ["SHP", "BOE", "LGD", "AUO", "SEC", "EDP"]):
                    logging.info(f"Skipping internal laptop display at index {i} ({pnp_id_str})")
                    continue

            model = "Unknown"
            brand = "Unknown"

            try:
                with monitor_obj:
                    caps = monitor_obj.get_vcp_capabilities()
                    model = caps.get('model', "Unknown")
            except:
                pass

            if model == "Unknown" and platform.system() == "Windows" and i < len(pnp_ids) and pnp_ids[i]:
                edid = read_edid(pnp_ids[i])
                if edid:
                    model = parse_edid(edid)

            if platform.system() == "Windows":
                if model != "Unknown":
                    model_upper = model.upper()
                    for prefix, brand_name in MODEL_BRAND_MAP.items():
                        if model_upper.startswith(prefix):
                            brand = brand_name
                            break
                    
                    if brand == "Unknown" and ("G2" in model_upper or "G3" in model_upper or "G4" in model_upper):
                        brand = "AOC"
                
                if brand == "Unknown" and i < len(pnp_ids):
                    try:
                        if pnp_ids[i]:
                            pnp_code = pnp_ids[i].split('\\')[1][:3].upper()
                            brand = PNP_IDS.get(pnp_code, "Unknown")
                    except Exception:
                        pass

            try:
                with monitor_obj:
                    caps = monitor_obj.get_vcp_capabilities()
                    inputs = caps.get('inputs', [])
                    input_names = [inp.name for inp in inputs]
                    
                    if not input_names:
                        input_names = ["DP1", "DP2", "mDP1", "HDMI1", "HDMI2", "DVI1", "VGA1", "USB-C1"]
                    
            except Exception as e:
                logging.warning(f"Could not get inputs for monitor {i}: {e}")
                input_names = ["DP1", "DP2", "mDP1", "HDMI1", "HDMI2", "DVI1", "VGA1", "USB-C1"]

            try:
                with monitor_obj:
                    current_input_obj = monitor_obj.get_input_source()
                    current_input = current_input_obj.name
            except Exception:
                current_input = "Unknown"

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
            self.status_label.configure(text="❌ Cannot switch: No monitor or input selected")
            return

        try:
            selected_monitor_id = self.selected_monitor_data['id']
            new_input = getattr(InputSource, new_input_str)
            with get_monitors()[selected_monitor_id] as monitor:
                monitor.set_input_source(new_input)

            self.status_label.configure(text=f"✅ Switched to {new_input_str}")
            logging.info(f"Successfully switched to {new_input_str}")

        except Exception as e:
            self.status_label.configure(text=f"❌ Error: {str(e)[:50]}")
            logging.error(f"Failed to switch input: {e}")

    def setup_global_hotkeys(self):
        """Setup global keyboard shortcuts"""
        try:
            for shortcut, (monitor_id, input_source) in self.shortcuts.items():
                keyboard.add_hotkey(
                    shortcut,
                    lambda m=monitor_id, i=input_source: self.handle_global_hotkey(m, i)
                )
            keyboard.add_hotkey('ctrl+shift+h', self.show_shortcuts_help)
            logging.info("Global hotkeys registered successfully")
        except Exception as e:
            logging.error(f"Failed to register global hotkeys: {e}")

    def handle_global_hotkey(self, monitor_id, input_source):
        """Handle global hotkey press"""
        try:
            monitors = get_monitors()
            if monitor_id < len(monitors):
                with monitors[monitor_id] as monitor:
                    if hasattr(InputSource, input_source):
                        input_obj = getattr(InputSource, input_source)
                        monitor.set_input_source(input_obj)
                        self.status_label.configure(text=f"✅ Hotkey: Switched to {input_source}")
                        logging.info(f"Hotkey: Switched monitor {monitor_id} to {input_source}")
        except Exception as e:
            self.status_label.configure(text=f"❌ Hotkey error: {str(e)[:40]}")
            logging.error(f"Hotkey error: {e}")

    def load_shortcuts(self):
        try:
            if os.path.exists(self.shortcuts_file):
                with open(self.shortcuts_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Error loading shortcuts: {e}")
        return None

    def save_shortcuts(self):
        try:
            with open(self.shortcuts_file, 'w') as f:
                json.dump(self.shortcuts, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving shortcuts: {e}")

    def load_favorites(self):
        try:
            if os.path.exists(self.favorites_file):
                with open(self.favorites_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Error loading favorites: {e}")
        return None

    def save_favorites(self):
        try:
            with open(self.favorites_file, 'w') as f:
                json.dump(self.favorites, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving favorites: {e}")

    def load_settings(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Error loading settings: {e}")
        return None

    def save_settings(self):
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving settings: {e}")

    def apply_theme(self):
        try:
            theme = self.settings.get("theme", "light")
            if theme in AVAILABLE_THEMES:
                customtkinter.set_appearance_mode(theme)
        except Exception as e:
            logging.error(f"Error applying theme: {e}")


    def add_favorite(self, name, monitor_id, input_source):
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
        try:
            if name not in self.favorites:
                self.status_label.configure(text=f"❌ Favorite '{name}' not found")
                return False
            
            monitor_id, input_source = self.favorites[name]
            monitors = get_monitors()
            
            if monitor_id >= len(monitors):
                self.status_label.configure(text=f"❌ Monitor {monitor_id} not found")
                return False
            
            with monitors[monitor_id] as monitor:
                if hasattr(InputSource, input_source):
                    input_obj = getattr(InputSource, input_source)
                    monitor.set_input_source(input_obj)
                    self.status_label.configure(text=f"✅ Switched to '{name}'")
                    logging.info(f"Switched to favorite '{name}'")
                    return True
        except Exception as e:
            self.status_label.configure(text=f"❌ Error: {str(e)[:40]}")
            logging.error(f"Error switching to favorite '{name}': {e}")
            return False

    def add_shortcut(self, shortcut_key, monitor_id, input_source):
        try:
            if not isinstance(shortcut_key, str) or not shortcut_key:
                return False
            monitor_id = int(monitor_id)
            if not isinstance(input_source, str) or not input_source:
                return False

            self.shortcuts[shortcut_key] = (monitor_id, input_source)
            self.save_shortcuts()
            
            try:
                keyboard.clear_all_hotkeys()
            except Exception:
                pass
            self.setup_global_hotkeys()

            logging.info(f"Added shortcut {shortcut_key} -> Monitor {monitor_id} : {input_source}")
            return True
        except Exception as e:
            logging.error(f"Failed to add shortcut: {e}")
            return False

    def refresh_favorites_buttons(self):
        """Rebuild favorites buttons"""
        for widget in self.favorites_scroll.winfo_children():
            widget.destroy()
        
        if not self.favorites:
            # When empty, show minimal placeholder text and keep small
            no_fav = customtkinter.CTkLabel(
                self.favorites_scroll,
                text="Click 'Manage' to add favorites",
                text_color="gray",
                font=("Arial", 10)
            )
            no_fav.pack(pady=8)
            # Keep minimal height when empty
            self.favorites_scroll.configure(height=40)
            return
        
        # Layout favorites in a responsive grid
        total = len(self.favorites)
        max_cols = 4  # number of columns per row
        row = 0
        col = 0

        for fav_name in self.favorites.keys():
            fav_btn = customtkinter.CTkButton(
                self.favorites_scroll,
                text=fav_name,
                command=lambda n=fav_name: self.switch_to_favorite(n),
                height=36,
                font=("Arial", 11)
            )
            fav_btn.grid(row=row, column=col, padx=6, pady=6, sticky="ew")

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

        # Calculate and set appropriate height based on number of rows
        rows = row + (1 if col > 0 else 0)
        rows = max(1, rows)
        per_row_height = 48
        new_height = 20 + rows * per_row_height
        self.favorites_scroll.configure(height=new_height)

        # Configure column weights for equal sizing
        for i in range(max_cols):
            try:
                self.favorites_scroll.grid_columnconfigure(i, weight=1)
            except Exception:
                pass

    def show_settings(self):
        """Show settings dialog"""
        settings_window = customtkinter.CTkToplevel(self)
        settings_window.title("Settings")
        settings_window.geometry("350x250")
        settings_window.resizable(False, False)
        settings_window.transient(self)
        settings_window.grab_set()
        
        frame = customtkinter.CTkFrame(settings_window)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        label = customtkinter.CTkLabel(frame, text="⚙️ Settings", font=("Arial", 16, "bold"))
        label.pack(pady=(0, 20))
        
        # Startup with Windows toggle
        startup_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
        startup_frame.pack(fill="x", pady=10)
        
        startup_label = customtkinter.CTkLabel(startup_frame, text="Start with Windows", font=("Arial", 12))
        startup_label.pack(side="left", padx=(0, 10))
        
        self.startup_toggle = customtkinter.CTkSwitch(
            startup_frame,
            text="",
            width=50,
            command=self.toggle_startup
        )
        self.startup_toggle.pack(side="right")
        
        # Check current startup status and set toggle accordingly
        if self.is_in_startup():
            self.startup_toggle.select()
        else:
            self.startup_toggle.deselect()

    def show_theme_settings(self):
        """Show theme settings dialog"""
        theme_window = customtkinter.CTkToplevel(self)
        theme_window.title("Theme Settings")
        theme_window.geometry("320x220")
        theme_window.resizable(False, False)
        theme_window.transient(self)
        theme_window.grab_set()
        
        frame = customtkinter.CTkFrame(theme_window)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        title = customtkinter.CTkLabel(frame, text="🎨 Application Theme", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 20))
        
        current_theme = self.settings.get("theme", "dark")
        theme_var = customtkinter.StringVar(value=current_theme)
        
        for theme in AVAILABLE_THEMES:
            theme_radio = customtkinter.CTkRadioButton(
                frame,
                text=theme.capitalize(),
                variable=theme_var,
                value=theme,
                font=("Arial", 12)
            )
            theme_radio.pack(anchor="w", padx=20, pady=8)
        
        button_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
        button_frame.pack(fill="x", pady=(20, 0))
        
        def apply_settings():
            self.settings["theme"] = theme_var.get()
            self.save_settings()
            self.apply_theme()
            self.status_label.configure(text="✅ Theme changed successfully")
            theme_window.destroy()
        
        apply_btn = customtkinter.CTkButton(button_frame, text="Apply", command=apply_settings, height=32)
        apply_btn.pack(side="left", padx=(0, 10), expand=True, fill="x")
        
        cancel_btn = customtkinter.CTkButton(button_frame, text="Cancel", command=theme_window.destroy, height=32)
        cancel_btn.pack(side="right", padx=(10, 0), expand=True, fill="x")

    def toggle_startup(self):
        """Toggle startup with Windows"""
        try:
            if self.startup_toggle.get():
                self.add_to_startup()
            else:
                self.remove_from_startup()
        except Exception as e:
            logging.error(f"Error toggling startup: {e}")
            messagebox.showerror("Error", f"Failed to update startup settings: {str(e)}")
    
    def is_in_startup(self):
        """Check if the application is in Windows startup"""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                                r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, "MonitorManager")
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                winreg.CloseKey(key)
                return False
        except Exception as e:
            logging.error(f"Error checking startup status: {e}")
            return False
    
    def add_to_startup(self):
        """Add the application to Windows startup"""
        try:
            # Get the path to the executable or script
            if getattr(sys, 'frozen', False):
                # Running as compiled executable
                exe_path = sys.executable
            else:
                # Running as script
                exe_path = os.path.abspath(sys.argv[0])
            
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, "MonitorManager", 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
            logging.info(f"Added to startup: {exe_path}")
            messagebox.showinfo("Success", "Application will now start with Windows")
        except Exception as e:
            logging.error(f"Error adding to startup: {e}")
            raise
    
    def remove_from_startup(self):
        """Remove the application from Windows startup"""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            try:
                winreg.DeleteValue(key, "MonitorManager")
                logging.info("Removed from startup")
                messagebox.showinfo("Success", "Application will no longer start with Windows")
            except FileNotFoundError:
                logging.warning("Entry not found in startup")
            finally:
                winreg.CloseKey(key)
        except Exception as e:
            logging.error(f"Error removing from startup: {e}")
            raise
    
    def create_tray_icon_image(self):
        """Create a simple icon for the system tray"""
        # Create a 64x64 icon with a monitor symbol
        width = 64
        height = 64
        image = Image.new('RGB', (width, height), 'white')
        dc = ImageDraw.Draw(image)
        
        # Draw a simple monitor shape
        dc.rectangle([10, 10, 54, 40], fill='black', outline='black')
        dc.rectangle([12, 12, 52, 38], fill='white', outline='white')
        dc.rectangle([28, 40, 36, 48], fill='black', outline='black')
        dc.rectangle([20, 48, 44, 52], fill='black', outline='black')
        
        return image
    
    def minimize_to_tray(self):
        """Minimize the window to system tray"""
        self.withdraw()  # Hide the window
        
        if self.tray_icon is None:
            # Create tray icon
            icon_image = self.create_tray_icon_image()
            menu = Menu(
                MenuItem('Show', self.show_window),
                MenuItem('Quit', self.quit_app)
            )
            self.tray_icon = Icon("Monitor Manager", icon_image, "Monitor Input Switcher", menu)
            
            # Run tray icon in a separate thread
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
    
    def on_minimize(self, event):
        """Handle window minimize event"""
        # Check if the window state changed to iconic (minimized)
        if event.widget == self and self.state() == 'iconic':
            self.after(10, self.minimize_to_tray)
    
    def show_window(self, icon=None, item=None):
        """Show the main window from system tray"""
        self.deiconify()  # Show the window
        self.lift()  # Bring to front
        self.focus_force()  # Give focus
    
    def quit_app(self, icon=None, item=None):
        """Quit the application completely"""
        self.is_quitting = True
        if self.tray_icon:
            self.tray_icon.stop()
        self.quit()
        self.destroy()

    def show_manage_favorites(self):
        """Show manage favorites dialog"""
        manage_window = customtkinter.CTkToplevel(self)
        manage_window.title("Manage Favorites")
        manage_window.resizable(False, False)
        manage_window.transient(self)
        manage_window.grab_set()
        
        main_frame = customtkinter.CTkFrame(manage_window)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        title = customtkinter.CTkLabel(main_frame, text="⭐ Manage Favorite Setups", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 15))
        
        # Current favorites section with dynamic sizing
        fav_section = customtkinter.CTkFrame(main_frame)
        fav_section.pack(fill="x", expand=False, pady=(0, 15))
        
        fav_header = customtkinter.CTkLabel(fav_section, text="Current Favorites:", font=("Arial", 12, "bold"))
        fav_header.pack(anchor="w", padx=12, pady=(12, 8))
        
        favorites_list_frame = customtkinter.CTkFrame(fav_section, height=60)
        favorites_list_frame.pack(fill="x", expand=False, padx=12, pady=(0, 12))
        favorites_list_frame.pack_propagate(False)
        
        def update_favorites_list():
            for widget in favorites_list_frame.winfo_children():
                widget.destroy()
            
            if not self.favorites:
                empty_label = customtkinter.CTkLabel(favorites_list_frame, text="No favorites saved yet.", text_color="gray")
                empty_label.pack(pady=20)
                # Keep small when empty
                favorites_list_frame.configure(height=60)
            else:
                # Calculate height based on number of favorites (each item ~45px)
                num_favorites = len(self.favorites)
                new_height = min(60 + (num_favorites * 45), 250)  # Cap at 250px
                favorites_list_frame.configure(height=new_height)
                
                for fav_name, (monitor_id, input_source) in self.favorites.items():
                    fav_frame = customtkinter.CTkFrame(favorites_list_frame)
                    fav_frame.pack(fill="x", pady=3)
                    
                    try:
                        mon = next((m for m in self.monitors_data if m.get('id') == monitor_id), None)
                        display_name = mon.get('display_name', f"Monitor {monitor_id}") if mon else f"Monitor {monitor_id}"
                    except Exception:
                        display_name = f"Monitor {monitor_id}"
                    
                    label_text = f"{fav_name}: {display_name} → {input_source}"
                    label = customtkinter.CTkLabel(fav_frame, text=label_text, font=("Arial", 11))
                    label.pack(side="left", padx=8, pady=6)
                    
                    delete_btn = customtkinter.CTkButton(
                        fav_frame, text="Delete", width=70, height=28,
                        command=lambda n=fav_name: delete_favorite(n),
                        fg_color=("#D32F2F", "#C62828"),
                        hover_color=("#C62828", "#B71C1C")
                    )
                    delete_btn.pack(side="right", padx=8)
            
            # Dynamically adjust window height based on actual content size
            manage_window.update_idletasks()
            required_height = main_frame.winfo_reqheight() + 30
            manage_window.geometry(f"480x{required_height}")
        
        def delete_favorite(name):
            self.remove_favorite(name)
            update_favorites_list()
            self.refresh_favorites_buttons()
        
        # Add new favorite section
        add_section = customtkinter.CTkFrame(main_frame)
        add_section.pack(fill="x", pady=(0, 0))
        
        add_header = customtkinter.CTkLabel(add_section, text="Add New Favorite:", font=("Arial", 12, "bold"))
        add_header.pack(anchor="w", padx=12, pady=(12, 8))
        
        form_frame = customtkinter.CTkFrame(add_section, fg_color="transparent")
        form_frame.pack(fill="x", padx=12, pady=(0, 12))
        
        # Name input
        name_label = customtkinter.CTkLabel(form_frame, text="Name:", font=("Arial", 11))
        name_label.grid(row=0, column=0, sticky="w", pady=(0, 8))
        
        name_var = customtkinter.StringVar(value="My Setup")
        name_entry = customtkinter.CTkEntry(form_frame, textvariable=name_var, height=32)
        name_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8), padx=(10, 0))
        
        # Monitor selection
        mon_label = customtkinter.CTkLabel(form_frame, text="Monitor:", font=("Arial", 11))
        mon_label.grid(row=1, column=0, sticky="w", pady=(0, 8))
        
        monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else []
        mon_choices = [f"{m.get('id')}: {m.get('display_name')}" for m in monitors_list] if monitors_list else ["0"]
        
        mon_var = customtkinter.StringVar(value=mon_choices[0])
        mon_menu = customtkinter.CTkOptionMenu(form_frame, variable=mon_var, values=mon_choices, height=32)
        mon_menu.grid(row=1, column=1, sticky="ew", pady=(0, 8), padx=(10, 0))
        
        # Input selection
        input_label = customtkinter.CTkLabel(form_frame, text="Input:", font=("Arial", 11))
        input_label.grid(row=2, column=0, sticky="w", pady=(0, 8))
        
        initial_inputs = monitors_list[0].get('inputs', []) if monitors_list else ["HDMI1", "DP1"]
        input_var = customtkinter.StringVar(value=initial_inputs[0] if initial_inputs else "HDMI1")
        input_menu = customtkinter.CTkOptionMenu(form_frame, variable=input_var, values=initial_inputs, height=32)
        input_menu.grid(row=2, column=1, sticky="ew", pady=(0, 8), padx=(10, 0))
        
        form_frame.grid_columnconfigure(1, weight=1)
        
        def update_input_options(*args):
            sel = mon_var.get()
            try:
                sel_id = int(sel.split(':', 1)[0].strip()) if ':' in sel else int(sel)
            except Exception:
                return
            
            inputs_for_sel = []
            for mon in monitors_list:
                if mon.get('id') == sel_id:
                    inputs_for_sel = mon.get('inputs', []) or []
                    break
            
            if not inputs_for_sel:
                inputs_for_sel = ["DP1", "HDMI1", "DP2", "HDMI2"]
            
            input_menu.configure(values=inputs_for_sel)
            input_var.set(inputs_for_sel[0])
        
        mon_var.trace_add('write', update_input_options)
        
        def add_fav():
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Error", "Please enter a favorite name", parent=manage_window)
                return
            
            sel = mon_var.get()
            try:
                monitor_id = int(sel.split(':', 1)[0].strip()) if ':' in sel else int(sel)
            except ValueError:
                messagebox.showerror("Error", "Invalid monitor selection", parent=manage_window)
                return
            
            input_source = input_var.get()
            
            if self.add_favorite(name, monitor_id, input_source):
                update_favorites_list()
                self.refresh_favorites_buttons()
                name_var.set("My Setup")
                messagebox.showinfo("Success", f"Favorite '{name}' added!", parent=manage_window)
            else:
                messagebox.showerror("Error", "Failed to add favorite", parent=manage_window)
        
        add_btn = customtkinter.CTkButton(form_frame, text="➕ Add Favorite", command=add_fav, height=36, font=("Arial", 12, "bold"))
        add_btn.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        
        update_favorites_list()

    def show_shortcuts_editor(self):
        """Show shortcuts editor dialog"""
        editor_window = customtkinter.CTkToplevel(self)
        editor_window.title("Keyboard Shortcuts")
        editor_window.geometry("520x600")
        editor_window.transient(self)
        editor_window.grab_set()
        
        main_frame = customtkinter.CTkFrame(editor_window)
        main_frame.pack(fill="both", expand=False, padx=15, pady=15)
        
        title = customtkinter.CTkLabel(main_frame, text="⌨️ Keyboard Shortcuts", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 10))
        
        instructions = customtkinter.CTkLabel(
            main_frame,
            text="Global hotkeys work even when this app is minimized.\nPress Ctrl+Shift+H anywhere to show shortcuts help.",
            font=("Arial", 10),
            text_color="gray"
        )
        instructions.pack(pady=(0, 15))

        # Shortcuts list section
        shortcuts_section = customtkinter.CTkFrame(main_frame)
        shortcuts_section.pack(fill="both", expand=True, pady=(0, 15))
        
        shortcuts_header = customtkinter.CTkLabel(shortcuts_section, text="Current Shortcuts:", font=("Arial", 12, "bold"))
        shortcuts_header.pack(anchor="w", padx=12, pady=(12, 8))
        
        shortcuts_frame = customtkinter.CTkScrollableFrame(shortcuts_section, height=280)
        shortcuts_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        
        def update_shortcuts_list():
            for widget in shortcuts_frame.winfo_children():
                widget.destroy()
                
            monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else []
            shown = 0
            
            for shortcut, (monitor_id, input_source) in self.shortcuts.items():
                mon = next((m for m in monitors_list if m.get('id') == monitor_id), None)
                if not mon:
                    continue

                shown += 1
                shortcut_frame = customtkinter.CTkFrame(shortcuts_frame)
                shortcut_frame.pack(fill="x", pady=3)

                display_name = mon.get('display_name', f"Monitor {monitor_id}")
                label = customtkinter.CTkLabel(
                    shortcut_frame,
                    text=f"{shortcut}: {display_name} → {input_source}",
                    font=("Arial", 11)
                )
                label.pack(side="left", padx=8, pady=6)

                btn_frame = customtkinter.CTkFrame(shortcut_frame, fg_color="transparent")
                btn_frame.pack(side="right", padx=8)

                edit_btn = customtkinter.CTkButton(
                    btn_frame, text="Edit", width=60, height=28,
                    command=lambda s=shortcut: edit_shortcut(s)
                )
                edit_btn.pack(side="left", padx=2)

                delete_btn = customtkinter.CTkButton(
                    btn_frame, text="Delete", width=60, height=28,
                    command=lambda s=shortcut: delete_shortcut(s),
                    fg_color=("#D32F2F", "#C62828"),
                    hover_color=("#C62828", "#B71C1C")
                )
                delete_btn.pack(side="left", padx=2)

            if shown == 0:
                notice = customtkinter.CTkLabel(shortcuts_frame, text="No shortcuts for currently connected monitors.", text_color="gray")
                notice.pack(pady=20)

        def record_shortcut(callback):
            dialog = customtkinter.CTkToplevel(editor_window)
            dialog.title("Record Shortcut")
            dialog.geometry("350x150")
            dialog.transient(editor_window)
            dialog.grab_set()
            
            label = customtkinter.CTkLabel(dialog, text="Press the desired key combination...", font=("Arial", 12))
            label.pack(pady=30)
            
            recorded_keys = []
            
            # Map of characters to their scan codes for number keys
            char_to_key = {
                '@': '2', '!': '1', '#': '3', '$': '4', '%': '5',
                '^': '6', '&': '7', '*': '8', '(': '9', ')': '0'
            }
            
            def on_key(event):
                if event.name not in recorded_keys and event.name not in ['ctrl', 'alt', 'shift']:
                    recorded_keys.extend(k for k in ['ctrl', 'alt', 'shift'] if keyboard.is_pressed(k))
                    
                    # Map shifted characters back to their base keys
                    key_name = char_to_key.get(event.name, event.name)
                    recorded_keys.append(key_name)
                    
                    shortcut = '+'.join(recorded_keys)
                    label.configure(text=f"Recorded: {shortcut}\n\nPress Enter to confirm or Esc to cancel")
                    
                    if event.name == 'enter':
                        dialog.destroy()
                        callback('+'.join(recorded_keys[:-1]))
                    elif event.name == 'esc':
                        dialog.destroy()
            
            keyboard.on_press(on_key)
            
        def add_new_shortcut():
            def on_shortcut(shortcut):
                if shortcut:
                    select_dialog = customtkinter.CTkToplevel(editor_window)
                    select_dialog.title("Configure Shortcut")
                    select_dialog.geometry("400x280")
                    select_dialog.transient(editor_window)
                    select_dialog.grab_set()

                    frame = customtkinter.CTkFrame(select_dialog)
                    frame.pack(fill="both", expand=True, padx=20, pady=20)

                    title = customtkinter.CTkLabel(frame, text=f"Shortcut: {shortcut}", font=("Arial", 13, "bold"))
                    title.pack(pady=(0, 15))

                    monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else []
                    mon_choices = [f"{m.get('id')}: {m.get('display_name')}" for m in monitors_list] if monitors_list else ["0"]

                    mon_label = customtkinter.CTkLabel(frame, text="Select Monitor:", font=("Arial", 11))
                    mon_label.pack(anchor="w", pady=(0, 5))

                    mon_var = customtkinter.StringVar(value=mon_choices[0])
                    mon_menu = customtkinter.CTkOptionMenu(frame, variable=mon_var, values=mon_choices, height=32)
                    mon_menu.pack(fill="x", pady=(0, 15))

                    input_label = customtkinter.CTkLabel(frame, text="Select Input:", font=("Arial", 11))
                    input_label.pack(anchor="w", pady=(0, 5))

                    initial_inputs = monitors_list[0].get('inputs', []) if monitors_list else ["HDMI1", "DP1"]
                    input_var = customtkinter.StringVar(value=initial_inputs[0] if initial_inputs else "HDMI1")
                    input_menu = customtkinter.CTkOptionMenu(frame, variable=input_var, values=initial_inputs, height=32)
                    input_menu.pack(fill="x", pady=(0, 20))

                    def save():
                        try:
                            sel = mon_var.get()
                            monitor_id = int(sel.split(':', 1)[0].strip()) if ':' in sel else int(sel)
                            input_source = input_var.get()
                            
                            if self.add_shortcut(shortcut, monitor_id, input_source):
                                update_shortcuts_list()
                                select_dialog.destroy()
                            else:
                                messagebox.showerror("Error", "Failed to save shortcut", parent=select_dialog)
                        except ValueError:
                            messagebox.showerror("Error", "Invalid monitor selection", parent=select_dialog)

                    save_btn = customtkinter.CTkButton(frame, text="Save Shortcut", command=save, height=36, font=("Arial", 12, "bold"))
                    save_btn.pack(fill="x")

                    def update_input_options(*args):
                        sel = mon_var.get()
                        try:
                            sel_id = int(sel.split(':', 1)[0].strip()) if ':' in sel else int(sel)
                        except Exception:
                            return
                        
                        inputs_for_sel = []
                        for mon in monitors_list:
                            if mon.get('id') == sel_id:
                                inputs_for_sel = mon.get('inputs', []) or []
                                break
                        
                        if not inputs_for_sel:
                            inputs_for_sel = ["DP1", "HDMI1", "DP2", "HDMI2"]
                        
                        input_menu.configure(values=inputs_for_sel)
                        input_var.set(inputs_for_sel[0])

                    mon_var.trace_add('write', update_input_options)
                    update_input_options()
            
            record_shortcut(on_shortcut)
            
        def edit_shortcut(shortcut):
            def on_new_shortcut(new_shortcut):
                if new_shortcut and new_shortcut != shortcut:
                    value = self.shortcuts.pop(shortcut)
                    self.shortcuts[new_shortcut] = value
                    self.save_shortcuts()
                    try:
                        keyboard.clear_all_hotkeys()
                    except:
                        pass
                    self.setup_global_hotkeys()
                    update_shortcuts_list()
            
            record_shortcut(on_new_shortcut)
            
        def delete_shortcut(shortcut):
            self.shortcuts.pop(shortcut)
            self.save_shortcuts()
            try:
                keyboard.clear_all_hotkeys()
            except:
                pass
            self.setup_global_hotkeys()
            update_shortcuts_list()
        
        # Buttons section
        buttons_frame = customtkinter.CTkFrame(main_frame, fg_color="transparent")
        buttons_frame.pack(fill="x")
        
        add_button = customtkinter.CTkButton(buttons_frame, text="➕ Add New Shortcut", command=add_new_shortcut, height=36, font=("Arial", 12, "bold"))
        add_button.pack(side="left", expand=True, fill="x", padx=(0, 8))
        
        def reset_defaults():
            self.shortcuts = self.default_shortcuts.copy()
            self.save_shortcuts()
            try:
                keyboard.clear_all_hotkeys()
            except:
                pass
            self.setup_global_hotkeys()
            update_shortcuts_list()
            
        reset_button = customtkinter.CTkButton(buttons_frame, text="↺ Reset to Defaults", command=reset_defaults, height=36, font=("Arial", 12))
        reset_button.pack(side="right", expand=True, fill="x", padx=(8, 0))
        
        update_shortcuts_list()

    def show_shortcuts_help(self):
        """Show shortcuts help dialog"""
        help_window = customtkinter.CTkToplevel(self)
        help_window.title("Keyboard Shortcuts Help")
        help_window.geometry("450x400")
        help_window.transient(self)
        help_window.grab_set()
        
        frame = customtkinter.CTkScrollableFrame(help_window)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        title = customtkinter.CTkLabel(frame, text="⌨️ Available Shortcuts", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 15))
        
        for shortcut, (monitor_id, input_source) in self.shortcuts.items():
            text = f"{shortcut}: Switch Monitor {monitor_id} to {input_source}"
            label = customtkinter.CTkLabel(frame, text=text, font=("Arial", 11))
            label.pack(anchor="w", pady=3)
            
        help_shortcut = customtkinter.CTkLabel(frame, text="\nctrl+shift+h: Show this help window", font=("Arial", 11, "bold"))
        help_shortcut.pack(anchor="w", pady=(15, 3))
            
        customize_btn = customtkinter.CTkButton(
            frame,
            text="Customize Shortcuts",
            command=lambda: [help_window.destroy(), self.show_shortcuts_editor()],
            height=36,
            font=("Arial", 12, "bold")
        )
        customize_btn.pack(pady=(20, 0), fill="x")


def cli_switch_input(monitor_index, input_name):
    """Switch input via command line interface"""
    try:
        monitors = get_monitors()
        if not monitors:
            print("Error: No monitors found")
            return False

        if monitor_index >= len(monitors):
            print(f"Error: Monitor index {monitor_index} is out of range. Found {len(monitors)} monitors.")
            return False

        with monitors[monitor_index] as monitor:
            if not hasattr(InputSource, input_name):
                print(f"Error: Invalid input source: {input_name}")
                print("Available inputs: " + ", ".join([x for x in dir(InputSource) if not x.startswith('_')]))
                return False

            new_input = getattr(InputSource, input_name)
            monitor.set_input_source(new_input)
            print(f"Successfully switched monitor {monitor_index} to {input_name}")
            return True

    except Exception as e:
        print(f"Error: {e}")
        return False


def cli_list_monitors():
    """List all available monitors and their inputs"""
    try:
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
        print(f"Error: {e}")


if __name__ == "__main__":
    try:
        import argparse
        parser = argparse.ArgumentParser(description='Monitor Input Switcher')
        
        parser.add_argument('--cli', action='store_true', help='Run in CLI mode')
        parser.add_argument('--list', action='store_true', help='List all monitors and their inputs')
        parser.add_argument('--monitor', type=int, help='Monitor index to control')
        parser.add_argument('--input', type=str, help='Input source to switch to (e.g., HDMI1, DP1)')
        
        args = parser.parse_args()

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
        else:
            app = App()
            app.mainloop()
            
    except Exception as e:
        logging.critical(f"Unhandled exception: {e}", exc_info=True)
        print(f"Critical error: {e}")