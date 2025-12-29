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
# FIX #4: Removed unused top-level 'import winreg' - it's imported locally in read_edid() where needed
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw
import ctypes

# Available themes for customtkinter
# "system" follows Windows light/dark mode setting
AVAILABLE_THEMES = ["dark", "light", "system"]

def set_dark_title_bar(window):
    """Set dark title bar on Windows 10/11 when in dark mode."""
    if platform.system() != 'Windows':
        return
    try:
        # Check if dark mode is currently active
        if customtkinter.get_appearance_mode().lower() == "dark":
            window.update()  # Ensure window is created
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass  # Silently fail on older Windows versions

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

# USB-C Display Detection:
# USB-C ports with DisplayPort Alt Mode are detected via DDC/CI VCP codes
# Standard InputSource enum covers: HDMI, DP, DVI, VGA, etc.
# Non-standard codes are displayed as INPUT_<code> for debugging

# FIX #5: VCP Input Source Codes (DDC/CI standard) - replaces magic numbers
VCP_INPUT_THUNDERBOLT = 26  # Code 0x1A - Thunderbolt (uses USB-C connector)
VCP_INPUT_USB_C = 27        # Code 0x1B - USB-C with DisplayPort Alt Mode

# Fallback brand detection from model
MODEL_BRAND_MAP = {
    "PA": "ASUS", "PG": "ASUS", "VG": "ASUS", "MG": "ASUS", "ROG": "ASUS", 
    "TUF": "ASUS", "BE": "ASUS",
    "AW": "Alienware", 
    "U24": "Dell", "U27": "Dell", "U34": "Dell", "P24": "Dell", "P27": "Dell", 
    "S24": "Dell", "S27": "Dell", "E24": "Dell", "E27": "Dell",
    "LG": "LG", "MP": "LG", "GP": "LG", "OLED": "LG", "GL": "LG", 
    "GN": "LG", "UK": "LG", "UM": "LG",
    "C24G": "Samsung", "C27G": "Samsung", "C32G": "Samsung", "ODYSSEY": "Samsung", 
    "LS": "Samsung", "F24": "Samsung", "F27": "Samsung",
    "27G": "AOC", "24G": "AOC", "22": "AOC", "Q27": "AOC", "CQ": "AOC",
    "C24": "AOC", "C27": "AOC", "C32": "AOC", "AG": "AOC", "AGON": "AOC",
    "VX": "ViewSonic", "VA": "ViewSonic", "VG": "ViewSonic",
    "XL": "BenQ", "EX": "BenQ", "PD": "BenQ", "EW": "BenQ", "ZOWIE": "BenQ", "GW": "BenQ",
    "XV": "Acer", "XF": "Acer", "KG": "Acer", "CB": "Acer", "XB": "Acer",
    "NITRO": "Acer", "PREDATOR": "Acer",
    "MAG": "MSI", "MPG": "MSI", "OPTIX": "MSI", "MEG": "MSI",
    "FI": "Gigabyte", "M27": "Gigabyte", "M32": "Gigabyte", "G27F": "Gigabyte", "AORUS": "Gigabyte",
    "OMEN": "HP", "X27": "HP", "Z27": "HP", "PAVILION": "HP",
    "BDM": "Philips", "PHL": "Philips", "PHI": "Philips"
}

# FIX #2: Removed static 'monitors = get_monitors()' that only ran at module load.
# Monitors are now refreshed dynamically in get_all_monitor_data() to detect
# newly connected/disconnected monitors.

# ===== RESPONSIVE SCALING SYSTEM =====
# Base values designed for 1080p (1920x1080) at 96 DPI
BASE_SCREEN_HEIGHT = 1080
BASE_DPI = 96

class UIScaler:
    """
    Calculates responsive UI scaling based on screen resolution and DPI.
    All sizes are relative to a 1080p baseline.
    Supports dynamic DPI changes when moving between monitors.
    """
    def __init__(self, root):
        self.root = root
        self._last_dpi = None
        self._calculate_scale_factors()
    
    def _calculate_scale_factors(self):
        """Calculate scaling factors based on screen metrics."""
        try:
            # Get screen dimensions
            screen_height = self.root.winfo_screenheight()
            
            # Get DPI (pixels per inch) - this reflects the current monitor's DPI
            dpi = self.root.winfo_fpixels('1i')
            self._last_dpi = dpi
            
            # Calculate scale factors
            # Resolution scale: how much bigger/smaller than 1080p
            self.resolution_scale = screen_height / BASE_SCREEN_HEIGHT
            
            # DPI scale: how much higher/lower than standard 96 DPI
            self.dpi_scale = dpi / BASE_DPI
            
            # Combined scale factor (weighted average)
            # Use DPI scale as primary, with resolution as secondary factor
            self.scale = (self.dpi_scale * 0.7) + (self.resolution_scale * 0.3)
            
            # Clamp scale to reasonable bounds (0.75x to 2.0x)
            self.scale = max(0.75, min(2.0, self.scale))
            
        except Exception:
            # Fallback to 1.0 scale if detection fails
            self.scale = 1.0
            self.resolution_scale = 1.0
            self.dpi_scale = 1.0
            self._last_dpi = BASE_DPI
    
    def check_dpi_change(self):
        """
        Check if DPI has changed (e.g., window moved to different monitor).
        Returns True if DPI changed and scaling was recalculated.
        """
        try:
            current_dpi = self.root.winfo_fpixels('1i')
            if self._last_dpi is not None and abs(current_dpi - self._last_dpi) > 1:
                self._calculate_scale_factors()
                return True
        except Exception:
            pass
        return False
    
    def size(self, base_value):
        """Scale a size value (width, height, padding, etc.)."""
        return int(base_value * self.scale)
    
    def font_size(self, base_size):
        """Scale a font size with slightly conservative scaling."""
        # Fonts scale a bit less aggressively to maintain readability
        font_scale = (self.scale - 1.0) * 0.8 + 1.0
        return int(base_size * font_scale)
    
    def font(self, family, size, weight=""):
        """Return a scaled font tuple."""
        scaled_size = self.font_size(size)
        if weight:
            return (family, scaled_size, weight)
        return (family, scaled_size)
    
    def window_size(self, base_width, base_height):
        """Calculate scaled window dimensions as a geometry string."""
        width = self.size(base_width)
        height = self.size(base_height)
        return f"{width}x{height}"

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class App(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        # Initialize UI scaler for responsive sizing
        self.ui = UIScaler(self)
        
        # Apply CustomTkinter's built-in scaling for all widgets
        # This ensures consistent sizing across different DPI displays
        customtkinter.set_widget_scaling(self.ui.scale)
        customtkinter.set_window_scaling(self.ui.scale)
        
        # Track last known window position for DPI change detection
        self._last_x = 0
        self._last_y = 0
        self._dpi_check_scheduled = False

        self.title("Monitor Manager")
        self.geometry(self.ui.window_size(520, 540))
        self.resizable(True, True)  # Allow window resizing
        
        try:
            self.iconbitmap(resource_path('monitor_manager_icon.ico'))
        except:
            pass
        
        # System tray setup
        self.tray_icon = None
        self.is_quitting = False
        
        # FIX #2: Instance-level monitors list (refreshed dynamically)
        self.monitors = []
        
        # Override window close behavior and minimize behavior
        self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        self.bind("<Unmap>", self.on_minimize)
        
        # Bind Configure event to detect when window moves (for DPI change detection)
        self.bind("<Configure>", self._on_window_configure)

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
            
        self.shortcuts = self.load_shortcuts() or {}
        self.favorites = self.load_favorites() or {}
        # Default window behavior is normal Windows behavior (no system tray)
        self.settings = self.load_settings() or {"theme": "system", "tray_on": "none"}
        self.apply_theme()
        
        # Apply tray behavior based on settings
        self.update_tray_behavior()
        
        self.setup_global_hotkeys()

        # ===== MAIN CONTAINER =====
        main_container = customtkinter.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=self.ui.size(15), pady=self.ui.size(10))

        # ===== HEADER =====
        header = customtkinter.CTkFrame(main_container, height=self.ui.size(50))
        header.pack(fill="x", pady=(0, self.ui.size(12)))
        header.pack_propagate(False)
        
        title_label = customtkinter.CTkLabel(
            header, 
            text="Monitor Input Switcher", 
            font=self.ui.font("Arial", 20, "bold")
        )
        title_label.pack(side="left", padx=self.ui.size(10), pady=self.ui.size(10))

        # Theme and Settings buttons in header
        btn_frame = customtkinter.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right", padx=self.ui.size(10))
        
        self.theme_button = customtkinter.CTkButton(
            btn_frame, 
            text="🎨", 
            command=self.show_theme_settings,
            width=self.ui.size(35),
            height=self.ui.size(35),
            font=self.ui.font("Arial", 16)
        )
        self.theme_button.pack(side="right", padx=2)
        
        self.shortcuts_button = customtkinter.CTkButton(
            btn_frame, 
            text="⌨", 
            command=self.show_shortcuts_editor,
            state="disabled",
            width=self.ui.size(35),
            height=self.ui.size(35),
            font=self.ui.font("Arial", 16)
        )
        self.shortcuts_button.pack(side="right", padx=2)

        # Add Settings button beside the keyboard shortcut button
        self.settings_button = customtkinter.CTkButton(
            btn_frame,
            text="⚙",  # Gear icon for settings
            command=self.show_settings,
            width=self.ui.size(35),
            height=self.ui.size(35),
            font=self.ui.font("Arial", 16)
            )
        self.settings_button.pack(side="right", padx=2)

        # Track open dialogs and loading state so they can be disabled during refresh
        self.settings_window = None
        self.theme_window = None
        self.manage_window = None
        self.editor_window = None
        self._loading_monitors = False

        # ===== MONITOR SELECTION CARD =====
        monitor_card = customtkinter.CTkFrame(main_container)
        monitor_card.pack(fill="x", pady=(0, self.ui.size(10)))
        
        monitor_header = customtkinter.CTkFrame(monitor_card, fg_color="transparent")
        monitor_header.pack(fill="x", padx=self.ui.size(12), pady=(self.ui.size(12), self.ui.size(8)))
        
        self.monitor_label = customtkinter.CTkLabel(
            monitor_header, 
            text="📺 Select Monitor", 
            font=self.ui.font("Arial", 13, "bold")
        )
        self.monitor_label.pack(side="left")
        
        self.refresh_button = customtkinter.CTkButton(
            monitor_header, 
            text="Refresh🔄",
            command=self.refresh_monitors,
            width=self.ui.size(30),
            height=self.ui.size(28),
            font=self.ui.font("Arial", 14)
        )
        self.refresh_button.pack(side="right")

        self.monitor_menu = customtkinter.CTkOptionMenu(
            monitor_card, 
            values=["Loading..."],
            command=self.update_inputs,
            height=self.ui.size(32),
            font=self.ui.font("Arial", 12)
        )
        self.monitor_menu.set("Loading...")
        self.monitor_menu.pack(fill="x", padx=self.ui.size(12), pady=(0, self.ui.size(12)))

        # ===== INPUT SOURCE CARD =====
        input_card = customtkinter.CTkFrame(main_container)
        input_card.pack(fill="x", pady=(0, self.ui.size(10)))
        
        self.input_label = customtkinter.CTkLabel(
            input_card, 
            text="🔌 Select Input Source", 
            font=self.ui.font("Arial", 13, "bold")
        )
        self.input_label.pack(anchor="w", padx=self.ui.size(12), pady=(self.ui.size(12), self.ui.size(8)))

        self.input_menu = customtkinter.CTkOptionMenu(
            input_card, 
            values=["Loading..."],
            height=self.ui.size(32),
            font=self.ui.font("Arial", 12)
        )
        self.input_menu.set("Loading...")
        self.input_menu.pack(fill="x", padx=self.ui.size(12), pady=(0, self.ui.size(12)))

        # ===== SWITCH BUTTON =====
        self.switch_button = customtkinter.CTkButton(
            main_container,
            text="⚡ Switch Input",
            command=self.switch_input,
            height=self.ui.size(42),
            font=self.ui.font("Arial", 14, "bold"),
            fg_color=("#2B7A0B", "#5FB041"),
            hover_color=("#246A09", "#52A038")
        )
        self.switch_button.pack(fill="x", pady=(0, self.ui.size(10)))

        # Progress bar (hidden by default)
        self.progress_bar = customtkinter.CTkProgressBar(main_container, mode='indeterminate')

        # ===== FAVORITES SECTION =====
        favorites_card = customtkinter.CTkFrame(main_container)
        # Don't expand by default; will grow when favorites are added
        favorites_card.pack(fill="x", expand=False, pady=(0, self.ui.size(10)))
        
        fav_header = customtkinter.CTkFrame(favorites_card, fg_color="transparent")
        fav_header.pack(fill="x", padx=self.ui.size(12), pady=(self.ui.size(12), self.ui.size(8)))
        
        self.favorites_label = customtkinter.CTkLabel(
            fav_header, 
            text="⭐ Quick Favorites", 
            font=self.ui.font("Arial", 13, "bold")
        )
        self.favorites_label.pack(side="left")

        self.manage_favorites_btn = customtkinter.CTkButton(
            fav_header,
            text="+ Manage",
            command=self.show_manage_favorites,
            state="disabled",
            width=self.ui.size(80),
            height=self.ui.size(26),
            font=self.ui.font("Arial", 11)
        )
        self.manage_favorites_btn.pack(side="right")

        # Favorites container - regular frame without scrolling, minimal height
        self.favorites_scroll = customtkinter.CTkFrame(
            favorites_card,
            fg_color="transparent",
            height=self.ui.size(40)
        )
        self.favorites_scroll.pack(fill="x", expand=False, padx=self.ui.size(12), pady=(0, self.ui.size(12)))
        self.favorites_scroll.pack_propagate(False)

        # ===== STATUS BAR =====
        status_frame = customtkinter.CTkFrame(main_container, height=self.ui.size(40))
        status_frame.pack(fill="x", pady=(0, 0))
        status_frame.pack_propagate(False)
        
        self.status_label = customtkinter.CTkLabel(
            status_frame,
            text="Ready",
            font=self.ui.font("Arial", 11),
            wraplength=self.ui.size(480)
        )
        self.status_label.pack(pady=self.ui.size(8))

        # ===== FOOTER =====
        footer = customtkinter.CTkLabel(
            main_container,
            text="By: LuqmanHakimAmiruddin@PDC",
            font=self.ui.font("Arial", 9),
            text_color="gray"
        )
        footer.pack(pady=(self.ui.size(5), 0))

        # Start initial refresh
        self.after(100, self.refresh_monitors)

    def refresh_monitors(self):
        self.status_label.configure(text="🔍 Detecting monitors...")
        self.progress_bar.pack(pady=(0, 10), fill="x")
        self.progress_bar.start()

        self.switch_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        # Gray-out related controls while loading monitor data
        self.monitor_menu.configure(values=["Loading..."], state="disabled")
        self.monitor_menu.set("Loading...")
        self.input_menu.configure(values=["Loading..."], state="disabled")
        self.input_menu.set("Loading...")
        # Disable shortcuts, settings, theme and manage favorites until monitors are detected
        try:
            self.shortcuts_button.configure(state="disabled")
        except Exception:
            pass
        try:
            self.settings_button.configure(state="disabled")
        except Exception:
            pass
        try:
            self.theme_button.configure(state="disabled")
        except Exception:
            pass
        try:
            self.manage_favorites_btn.configure(state="disabled")
        except Exception:
            pass

        # Mark loading and disable any open dialogs so users can't interact with them while refresh is in progress
        self._loading_monitors = True
        try:
            self._set_toplevels_state('disabled')
        except Exception:
            pass

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
            # Enable monitor and input controls now that data is available
            try:
                self.monitor_menu.configure(state="normal")
            except Exception:
                pass
            try:
                self.input_menu.configure(state="normal")
            except Exception:
                pass
            self.update_inputs(self.monitor_names[0])
            self.status_label.configure(text="✅ Ready to switch inputs")
            self.shortcuts_button.configure(state="normal")
            self.manage_favorites_btn.configure(state="normal")
            try:
                self.settings_button.configure(state="normal")
            except Exception:
                pass
            try:
                self.theme_button.configure(state="normal")
            except Exception:
                pass
            self.refresh_favorites_buttons()
        else:
            self.monitor_menu.set("No monitors detected")
            try:
                self.monitor_menu.configure(state="disabled")
            except Exception:
                pass
            self.input_menu.configure(values=[])
            self.input_menu.set("")
            try:
                self.input_menu.configure(state="disabled")
            except Exception:
                pass
            self.status_label.configure(text="❌ No monitors found. Check connections and refresh.")
            self.shortcuts_button.configure(state="disabled") #grayout for button (normal/disabled)
            self.manage_favorites_btn.configure(state="disabled") #grayout for button (normal/disabled)
            # Keep settings and theme available so the user can change preferences even if no monitors are found
            try:
                self.settings_button.configure(state="normal")
            except Exception:
                pass
            try:
                self.theme_button.configure(state="normal")
            except Exception:
                pass

        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.switch_button.configure(state="normal")
        self.refresh_button.configure(state="normal")

        # Clear loading flag and re-enable any dialogs that were disabled
        self._loading_monitors = False
        try:
            self._set_toplevels_state('normal')
        except Exception:
            pass
    
    def get_all_monitor_data(self):
        """Get all monitor data - keeping original implementation"""
        all_data = []
        pnp_ids = []

        # FIX #2: Refresh monitors list each time this method is called
        # This ensures newly connected/disconnected monitors are detected
        self.monitors = get_monitors()

        try:
            logging.info(f"Found {len(self.monitors)} monitors.")
            
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

        # FIX #1: Collect PnP IDs from WMI once (moved outside the monitor loop)
        # Previously this was nested inside 'for monitor in monitors:' and used 'for monitor in wmi_monitors:'
        # which shadowed the outer variable, causing only 1 monitor to be processed.
        if platform.system() == "Windows":
            try:
                c = wmi.WMI()
                wmi_monitors = c.Win32_DesktopMonitor()
                for wmi_mon in wmi_monitors:
                    pnp_ids.append(getattr(wmi_mon, 'PNPDeviceID', None))
            except Exception as e:
                logging.error(f"Failed to get device information from WMI: {e}")
        logging.info(f"WMI PnP IDs: {pnp_ids}")

        def read_edid(pnp_id):
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\\CurrentControlSet\\Enum\\" + pnp_id + r"\Device Parameters"
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

        for i, monitor_obj in enumerate(self.monitors):
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
                # Try to get brand from PNP code first
                if brand == "Unknown" and i < len(pnp_ids):
                    try:
                        if pnp_ids[i]:
                            pnp_code = pnp_ids[i].split('\\')[1][:3].upper()
                            brand = PNP_IDS.get(pnp_code, "Unknown")
                    except Exception:
                        pass
               
                # If PNP lookup failed, try model prefix matching as fallback
                if brand == "Unknown" and model != "Unknown":
                    model_upper = model.upper()
                    for prefix, brand_name in MODEL_BRAND_MAP.items():
                        if model_upper.startswith(prefix):
                            brand = brand_name
                            break

            try:
                input_names = []
                with monitor_obj:
                    caps = monitor_obj.get_vcp_capabilities()
                    inputs = caps.get('inputs', [])
                    for inp in inputs:
                        if hasattr(inp, 'name'):
                            input_names.append(inp.name)
                        elif isinstance(inp, int):
                            # USB-C with DisplayPort Alt Mode uses code 27 (0x1B)
                            # Thunderbolt also uses USB-C connector with DP protocol
                            if inp == VCP_INPUT_USB_C:
                                input_names.append("USB-C")
                            elif inp == VCP_INPUT_THUNDERBOLT:
                                input_names.append("THUNDERBOLT")
                            else:
                                # Unknown input code - display as is for debugging
                                input_names.append(f"INPUT_{inp}")

            except Exception as e:
                logging.warning(f"Could not get inputs for monitor {i}: {e}")

            #Get current input
            try:
                with monitor_obj:
                    current_input = monitor_obj.get_input_source()
                    if hasattr(current_input, 'value'):
                        current_code = current_input.value
                        current_name = current_input.name if hasattr(current_input, 'name') else str(current_input)
                    else:
                        current_code = int(current_input)
                        current_name = get_input_name(current_code)
            except Exception as e:
                    logging.warning(f"⚠️  Could not read current input: {e}")
                    current_code = None
                    current_name = "Unknown"

            all_data.append({
                "display_name": f"{brand} - {model}",
                "inputs": input_names,
                "id": i,
                "current_input": current_name
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

    def move_app_if_on_switching_monitor(self, monitor_id):
        """Move app window to another monitor if it's on the monitor being switched"""
        try:
            all_screens = get_screen_info()
            screen_to_switch = all_screens[monitor_id] if monitor_id < len(all_screens) else None
            
            if not screen_to_switch:
                return
            
            # Get app's current screen
            app_x = self.winfo_x()
            app_y = self.winfo_y()
            app_current_screen = None
            for screen in all_screens:
                if (screen.x <= app_x < screen.x + screen.width and 
                    screen.y <= app_y < screen.y + screen.height):
                    app_current_screen = screen
                    break
            
            # If the app is on the screen we're about to switch, move it to another screen
            if app_current_screen and app_current_screen == screen_to_switch:
                other_screens = [s for s in all_screens if s != screen_to_switch]
                if other_screens:
                    new_screen = other_screens[0]
                    self.geometry(f"+{new_screen.x}+{new_screen.y}")
                    self.update_idletasks()  # Ensure the move is processed
        except Exception as e:
            logging.warning(f"Failed to move app window: {e}")

    def switch_input(self):
        new_input_str = self.input_menu.get()
        logging.info(f"Input name: {new_input_str}")
        if new_input_str == "No inputs found" or not hasattr(self, 'selected_monitor_data'):
            self.status_label.configure(text="❌ Cannot switch: No monitor or input selected")
            return

        try:
            selected_monitor_id = self.selected_monitor_data['id']
            logging.info(f"Current Monitor ID: {selected_monitor_id}")

            # Move app if it's on the monitor being switched
            self.move_app_if_on_switching_monitor(selected_monitor_id)

            # Handle custom input codes (USB-C, Thunderbolt, etc.)
            if new_input_str == "USB-C":
                new_input = VCP_INPUT_USB_C
            elif new_input_str == "THUNDERBOLT":
                new_input = VCP_INPUT_THUNDERBOLT
            elif new_input_str.startswith("INPUT_"):
                # Handle unknown input codes (INPUT_XX format)
                new_input = int(new_input_str.split('_')[1])
            else:
                # Standard InputSource enum values
                new_input = getattr(InputSource, new_input_str)
            logging.info(f"Input name: {new_input}")

            with self.monitors[selected_monitor_id] as monitor:
                logging.info(f"monitor: {monitor}")
                monitor.set_input_source(new_input)
            logging.info(f"Input name after: {new_input}")

            # Include monitor brand/model in status message
            monitor_name = self.selected_monitor_data.get('display_name', f'Monitor {selected_monitor_id}')
            self.status_label.configure(text=f"✅ {monitor_name}: Switched to {new_input_str}")
            logging.info(f"Successfully switched {monitor_name} to {new_input_str}")

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
            if monitor_id < len(self.monitors):
                # Get monitor display name (brand - model)
                monitor_name = f"Monitor {monitor_id}"
                for data in self.monitors_data:
                    if data.get('id') == monitor_id:
                        monitor_name = data.get('display_name', monitor_name)
                        break
                
                # Move app if it's on the monitor being switched
                self.move_app_if_on_switching_monitor(monitor_id)
                
                with self.monitors[monitor_id] as monitor:
                    # Handle custom input codes
                    if input_source == "USB-C":
                        input_obj = VCP_INPUT_USB_C
                    elif input_source == "THUNDERBOLT":
                        input_obj = VCP_INPUT_THUNDERBOLT
                    elif input_source.startswith("INPUT_"):
                        input_obj = int(input_source.split('_')[1])
                    elif hasattr(InputSource, input_source):
                        input_obj = getattr(InputSource, input_source)
                    else:
                        logging.error(f"Unknown input source: {input_source}")
                        return
                    
                    monitor.set_input_source(input_obj)
                    self.status_label.configure(text=f"✅ {monitor_name}: Switched to {input_source}")
                    logging.info(f"Hotkey: Switched {monitor_name} to {input_source}")
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
            theme = self.settings.get("theme", "system")
            if theme in AVAILABLE_THEMES:
                # "system" tells customtkinter to follow Windows theme
                customtkinter.set_appearance_mode(theme)
        except Exception as e:
            logging.error(f"Error applying theme: {e}")

    def _recursive_set_state(self, widget, state):
        """Recursively set state for widgets that support it."""
        try:
            widget.configure(state=state)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._recursive_set_state(child, state)

    def _set_toplevels_state(self, state):
        """Set the enabled/disabled state for any open Toplevel dialogs."""
        for attr in ('settings_window', 'theme_window', 'manage_window', 'editor_window'):
            win = getattr(self, attr, None)
            if win:
                try:
                    self._recursive_set_state(win, state)
                except Exception:
                    logging.debug(f"Failed to set state {state} for {attr}")


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

    # FIX #6 & #7: Helper methods for favorite dialogs - reduces duplicate code and adds validation
    
    def _validate_favorite_name(self, name, exclude_name=None):
        """
        FIX #7: Validate favorite name with proper rules.
        Returns (is_valid, error_message) tuple.
        
        Args:
            name: The name to validate
            exclude_name: Name to exclude from duplicate check (for edit mode)
        """
        # Maximum characters allowed for favorite name (keeps UI buttons visible)
        MAX_FAVORITE_NAME_LENGTH = 20
        
        if not name:
            return False, "Please enter a favorite name"
        
        # Check length - reduced to keep edit/delete buttons visible in UI
        if len(name) > MAX_FAVORITE_NAME_LENGTH:
            return False, f"Name must be {MAX_FAVORITE_NAME_LENGTH} characters or less"
        
        # Check for invalid characters that could break JSON or cause issues
        invalid_chars = ['\\', '/', '"', '\n', '\r', '\t']
        for char in invalid_chars:
            if char in name:
                return False, f"Name cannot contain '{char}' character"
        
        # Check for duplicates (case-insensitive)
        for existing_name in self.favorites.keys():
            if existing_name.lower() == name.lower():
                if exclude_name is None or existing_name.lower() != exclude_name.lower():
                    return False, f"A favorite named '{existing_name}' already exists"
        
        return True, None

    def _get_inputs_for_monitor(self, monitor_id):
        """Get available inputs for a given monitor ID."""
        monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else []
        for mon in monitors_list:
            if mon.get('id') == monitor_id:
                return mon.get('inputs', []) or []
        return []

    def _get_monitor_choices(self):
        """Get list of monitor choices for dropdowns."""
        monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else []
        if monitors_list:
            return [f"{m.get('id')}: {m.get('display_name')}" for m in monitors_list]
        return ["0"]

    def _parse_monitor_selection(self, selection):
        """Parse monitor ID from dropdown selection string."""
        try:
            return int(selection.split(':', 1)[0].strip()) if ':' in selection else int(selection)
        except (ValueError, AttributeError):
            return 0

    def _center_dialog_on_parent(self, dialog, parent, width=None, height=None):
        """
        Center a dialog window on its parent window.
        Works correctly across multiple monitors with different positions.
        
        Args:
            dialog: The dialog window to center
            parent: The parent window to center on
            width: Optional base width (will be scaled and use dialog's requested width if not specified)
            height: Optional base height (will be scaled and use dialog's requested height if not specified)
        """
        # Ensure both parent and dialog geometries are fully calculated
        parent.update_idletasks()
        dialog.update_idletasks()
        
        # Scale the provided dimensions, or use dialog's requested size
        dlg_width = self.ui.size(width) if width else dialog.winfo_reqwidth()
        dlg_height = self.ui.size(height) if height else dialog.winfo_reqheight()
        
        # Get parent's absolute position on the virtual screen
        # Use winfo_x/winfo_y which give the window's top-left position
        # These work correctly on multi-monitor setups including negative coordinates
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        
        # Calculate center position relative to parent
        # This will correctly position on whatever monitor the parent is on
        x = parent_x + (parent_width - dlg_width) // 2
        y = parent_y + (parent_height - dlg_height) // 2
        
        # Allow negative coordinates for monitors to the left/above primary
        # Only ensure the dialog is at least partially visible
        dialog.geometry(f"{dlg_width}x{dlg_height}+{x}+{y}")

    def switch_to_favorite(self, name):
        try:
            if name not in self.favorites:
                self.status_label.configure(text=f"❌ Favorite '{name}' not found")
                return False

            monitor_id, input_source = self.favorites[name]

            if monitor_id >= len(self.monitors):
                self.status_label.configure(text=f"❌ Monitor {monitor_id} not found")
                return False

            # Get monitor display name (brand - model)
            monitor_name = f"Monitor {monitor_id}"
            for data in self.monitors_data:
                if data.get('id') == monitor_id:
                    monitor_name = data.get('display_name', monitor_name)
                    break

            # Move app if it's on the monitor being switched
            self.move_app_if_on_switching_monitor(monitor_id)

            # Normalize input_source for enum or code
            input_obj = None
            # Try enum attribute (e.g., HDMI1, DP1, USB_C, THUNDERBOLT)
            normalized = input_source.replace("-", "_").replace(" ", "_").upper()
            if hasattr(InputSource, normalized):
                input_obj = getattr(InputSource, normalized)
            elif input_source.upper() == "USB-C":
                # Fallback to known code for USB-C
                input_obj = 27  # VCP_INPUT_USB_C
            elif input_source.upper() == "THUNDERBOLT":
                input_obj = 26  # VCP_INPUT_THUNDERBOLT
            else:
                # Try to parse as int code (e.g., INPUT_27)
                try:
                    if input_source.startswith("INPUT_"):
                        input_obj = int(input_source.split("_")[-1])
                except Exception:
                    pass

            with self.monitors[monitor_id] as monitor:
                if input_obj is not None:
                    monitor.set_input_source(input_obj)
                    self.status_label.configure(text=f"✅ {monitor_name}: Switched to '{name}'")
                    logging.info(f"Switched {monitor_name} to favorite '{name}'")
                    return True
                else:
                    self.status_label.configure(text=f"❌ Unknown input source '{input_source}'")
                    logging.error(f"Unknown input source '{input_source}' for favorite '{name}'")
                    return False
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
                font=self.ui.font("Arial", 10)
            )
            no_fav.pack(pady=self.ui.size(8))
            # Keep minimal height when empty
            self.favorites_scroll.configure(height=self.ui.size(40))
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
                height=self.ui.size(36),
                font=self.ui.font("Arial", 11)
            )
            fav_btn.grid(row=row, column=col, padx=self.ui.size(6), pady=self.ui.size(6), sticky="ew")

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

        # Calculate and set appropriate height based on number of rows
        rows = row + (1 if col > 0 else 0)
        rows = max(1, rows)
        per_row_height = self.ui.size(48)
        new_height = self.ui.size(20) + rows * per_row_height
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
        # Track this window so it can be disabled during refresh
        self.settings_window = settings_window
        settings_window.title("Settings")
        # Slightly larger window to accommodate increased font sizes
        settings_window.resizable(False, False)
        settings_window.transient(self)
        settings_window.grab_set()
        self._center_dialog_on_parent(settings_window, self, 460, 420)
        # Clear reference when window is destroyed
        settings_window.bind('<Destroy>', lambda e: setattr(self, 'settings_window', None))
        
        frame = customtkinter.CTkFrame(settings_window)
        frame.pack(fill="both", expand=True, padx=self.ui.size(20), pady=self.ui.size(20))
        
        label = customtkinter.CTkLabel(frame, text="⚙️ Tray Settings", font=self.ui.font("Arial", 16, "bold"))
        label.pack(pady=(0, self.ui.size(10)))
        
        # System Tray Behavior
        tray_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
        tray_frame.pack(fill="x", pady=self.ui.size(5))
        
        tray_title = customtkinter.CTkLabel(tray_frame, text=" Window Behavior", font=self.ui.font("Arial", 14, "bold"))
        tray_title.pack(anchor="w", pady=(0, 3))
        
        # Pick readable text colors based on current appearance mode
        appearance = customtkinter.get_appearance_mode()
        normal_text_color = "#000000" if appearance == "Light" else "#EDEDED"
        note_text_color = "#000000" if appearance == "Light" else "#EDEDED"

        tray_desc = customtkinter.CTkLabel(
            tray_frame, 
            text="Choose what happens when you minimize or close the window:", 
            font=self.ui.font("Arial", 11),
            text_color=normal_text_color
        )
        tray_desc.pack(anchor="w", pady=(0, self.ui.size(10)))
        
        # Default to normal (no system tray) behavior when settings missing
        tray_on = self.settings.get("tray_on", "none")
        self.tray_radio_var = customtkinter.StringVar(value=tray_on)
        
        # Put the 'Normal Windows behavior' option first so it's shown on top
        none_radio = customtkinter.CTkRadioButton(
            tray_frame,
            text="Normal Windows behavior (no system tray)",
            variable=self.tray_radio_var,
            value="none",
            command=self.update_tray_setting
        )
        none_radio.pack(anchor="w", pady=3, padx=5)

        close_radio = customtkinter.CTkRadioButton(
            tray_frame,
            text="When I click Close (X) → Hide to tray (keep running)",
            variable=self.tray_radio_var,
            value="close",
            command=self.update_tray_setting
        )
        close_radio.pack(anchor="w", pady=3, padx=5)
        
        minimize_radio = customtkinter.CTkRadioButton(
            tray_frame,
            text="When I click Minimize (_) → Hide to tray (keep running)",
            variable=self.tray_radio_var,
            value="minimize",
            command=self.update_tray_setting
        )
        minimize_radio.pack(anchor="w", pady=3, padx=5) 
        
        both_radio = customtkinter.CTkRadioButton(
            tray_frame,
            text="Both Close and Minimize → Hide to tray (keep running)",
            variable=self.tray_radio_var,
            value="both",
            command=self.update_tray_setting
        )
        both_radio.pack(anchor="w", pady=3, padx=5)
        
        # Add helpful note in highlighted box
        note_frame = customtkinter.CTkFrame(tray_frame, fg_color=("#E3F2FD", "#1E3A5F"))
        note_frame.pack(fill="x", pady=(12, 0))
        
        note_icon = customtkinter.CTkLabel(
            note_frame,
            text="💡",
            font=self.ui.font("Arial", 14)
        )
        note_icon.pack(side="left", padx=(self.ui.size(10), self.ui.size(5)), pady=self.ui.size(8))
        
        note_text = customtkinter.CTkLabel(
            note_frame,
            text="When hidden in tray, right-click the tray icon to show or quit",
            font=self.ui.font("Arial", 11, "bold"),
            justify="left",
            wraplength=self.ui.size(360),
            text_color=note_text_color
        )
        note_text.pack(side="left", padx=(self.ui.size(5), self.ui.size(10)), pady=self.ui.size(8))

        # Save / Cancel buttons for settings (centered)
        btn_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(self.ui.size(12), 0))

        def save_and_apply_settings():
            # Update and persist tray setting, then show confirmation
            try:
                self.update_tray_setting()
                try:
                    messagebox.showinfo("Success", "Settings saved!", parent=settings_window)
                except Exception:
                    pass
                settings_window.destroy()
            except Exception as e:
                logging.error(f"Failed to save settings: {e}")
                try:
                    messagebox.showerror("Error", "Failed to save settings.", parent=settings_window)
                except Exception:
                    pass

        # Center the buttons by placing them in an inner centered frame
        center_frame = customtkinter.CTkFrame(btn_frame, fg_color="transparent")
        center_frame.pack(anchor="center")

        cancel_btn = customtkinter.CTkButton(
            center_frame,
            text="Cancel",
            command=settings_window.destroy,
            height=self.ui.size(36),
            width=self.ui.size(110),
            fg_color=("#D32F2F", "#C62828"),
            hover_color=("#C62828", "#B71C1C")
        )
        cancel_btn.pack(side="left", padx=self.ui.size(8))

        save_btn = customtkinter.CTkButton(center_frame, text="Save", command=save_and_apply_settings, height=self.ui.size(36), width=self.ui.size(110))
        save_btn.pack(side="left", padx=self.ui.size(8))

    def show_theme_settings(self):
        """Show theme settings dialog"""
        theme_window = customtkinter.CTkToplevel(self)
        # Track open theme dialog for disabling during refresh
        self.theme_window = theme_window
        theme_window.title("Theme Settings")
        theme_window.resizable(False, False)
        theme_window.transient(self)
        theme_window.grab_set()
        self._center_dialog_on_parent(theme_window, self, 320, 260)
        theme_window.bind('<Destroy>', lambda e: setattr(self, 'theme_window', None))
        set_dark_title_bar(theme_window)  # Apply dark title bar if in dark mode
        
        frame = customtkinter.CTkFrame(theme_window)
        frame.pack(fill="both", expand=True, padx=self.ui.size(20), pady=self.ui.size(20))
        
        title = customtkinter.CTkLabel(frame, text="🎨 Application Theme", font=self.ui.font("Arial", 16, "bold"))
        title.pack(pady=(0, self.ui.size(20)))
        
        current_theme = self.settings.get("theme", "dark")
        theme_var = customtkinter.StringVar(value=current_theme)
        
        # Theme options with display labels
        theme_labels = {
            "dark": "Dark",
            "light": "Light",
            "system": "System (follow Windows)"
        }
        
        for theme in AVAILABLE_THEMES:
            theme_radio = customtkinter.CTkRadioButton(
                frame,
                text=theme_labels.get(theme, theme.capitalize()),
                variable=theme_var,
                value=theme,
                font=self.ui.font("Arial", 12)
            )
            theme_radio.pack(anchor="w", padx=self.ui.size(20), pady=self.ui.size(8))
        
        # Save / Cancel buttons centered with spacing like the Window Behavior setting
        btn_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(self.ui.size(12), 0))

        def apply_settings():
            self.settings["theme"] = theme_var.get()
            self.save_settings()
            self.apply_theme()
            self.status_label.configure(text="✅ Theme changed successfully")
            theme_window.destroy()

        # Center the buttons by placing them in an inner centered frame
        center_frame = customtkinter.CTkFrame(btn_frame, fg_color="transparent")
        center_frame.pack(anchor="center")

        cancel_btn = customtkinter.CTkButton(
            center_frame,
            text="Cancel",
            command=theme_window.destroy,
            height=self.ui.size(36),
            width=self.ui.size(110),
            fg_color=("#D32F2F", "#C62828"),
            hover_color=("#C62828", "#B71C1C")
        )
        cancel_btn.pack(side="left", padx=self.ui.size(8))

        apply_btn = customtkinter.CTkButton(
            center_frame,
            text="Apply",
            command=apply_settings,
            height=self.ui.size(36),
            width=self.ui.size(110),
            fg_color=("#2B7A0B", "#5FB041"),
            hover_color=("#246A09", "#52A038")
        )
        apply_btn.pack(side="left", padx=self.ui.size(8))

    def update_tray_setting(self):
        """Update system tray behavior setting"""
        self.settings["tray_on"] = self.tray_radio_var.get()
        self.save_settings()
        self.update_tray_behavior()
        logging.info(f"Tray behavior set to: {self.settings['tray_on']}")
    
    def update_tray_behavior(self):
        """Update window behaviors based on tray_on setting"""
        # Default to normal window behavior (no system tray)
        tray_on = self.settings.get("tray_on", "none")
        
        # Update close button behavior
        if tray_on in ["close", "both"]:
            self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        else:
            self.protocol("WM_DELETE_WINDOW", self.quit_app)
        
        # Update minimize behavior binding
        try:
            self.unbind("<Unmap>")
        except:
            pass
        if tray_on in ["minimize", "both"]:
            self.bind("<Unmap>", self.on_minimize)
    
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
            # Only minimize to tray if setting allows it (default to normal behavior)
            tray_on = self.settings.get("tray_on", "none")
            if tray_on in ["minimize", "both"]:
                self.after(10, self.minimize_to_tray)
    
    def _on_window_configure(self, event):
        """
        Handle window configuration changes (move, resize).
        Checks if window moved to a different monitor with different DPI.
        """
        # Only process events for the main window, not child widgets
        if event.widget != self:
            return
        
        # Check if window position changed significantly (moved to different area)
        x, y = self.winfo_x(), self.winfo_y()
        if abs(x - self._last_x) > 50 or abs(y - self._last_y) > 50:
            self._last_x, self._last_y = x, y
            
            # Debounce DPI check to avoid excessive recalculations during drag
            if not self._dpi_check_scheduled:
                self._dpi_check_scheduled = True
                self.after(500, self._check_and_apply_dpi_change)
    
    def _check_and_apply_dpi_change(self):
        """Check if DPI changed and re-apply scaling if needed."""
        self._dpi_check_scheduled = False
        
        if self.ui.check_dpi_change():
            # DPI changed - update CustomTkinter's scaling
            logging.info(f"DPI change detected. New scale: {self.ui.scale:.2f}")
            customtkinter.set_widget_scaling(self.ui.scale)
            customtkinter.set_window_scaling(self.ui.scale)
            
            # Update status to inform user
            self.status_label.configure(text=f"🖥️ Display scaling updated ({self.ui.scale:.0%})")
    
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
        # Track this window for temporary disabling during refresh
        self.manage_window = manage_window
        manage_window.title("Manage Favorites")
        manage_window.resizable(False, False)
        manage_window.transient(self)
        manage_window.grab_set()
        self._center_dialog_on_parent(manage_window, self, 450, 500)
        manage_window.bind('<Destroy>', lambda e: setattr(self, 'manage_window', None))
        
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

                    edit_btn = customtkinter.CTkButton(
                        fav_frame, text="Edit", width=70, height=28,
                        command=lambda n=fav_name: edit_favorite(n),
                        fg_color=("#1976D2", "#1565C0"),
                        hover_color=("#1565C0", "#0D47A1")
                    )
                    edit_btn.pack(side="right", padx=8)
            
            # Dynamically adjust window height based on actual content size
            manage_window.update_idletasks()
            required_height = main_frame.winfo_reqheight() + 30
            manage_window.geometry(f"480x{required_height}")
        
        def delete_favorite(name):
            try:
                try:
                    confirm = messagebox.askyesno("Confirm Delete", f"Delete favorite '{name}'?", parent=manage_window)
                except Exception:
                    confirm = True

                if not confirm:
                    return

                if self.remove_favorite(name):
                    update_favorites_list()
                    self.refresh_favorites_buttons()
                    try:
                        messagebox.showinfo("Success", f"Favorite '{name}' removed!", parent=manage_window)
                    except Exception:
                        pass
                else:
                    try:
                        messagebox.showerror("Error", f"Failed to remove favorite '{name}'", parent=manage_window)
                    except Exception:
                        pass
            except Exception as e:
                logging.error(f"Failed to remove favorite {name}: {e}")

        def edit_favorite(name):
            """Open an edit dialog to rename or change monitor/input for a favorite"""
            # FIX #6: Refactored to use helper methods, reducing duplicate code
            current = self.favorites.get(name)
            if not current:
                messagebox.showerror("Error", f"Favorite '{name}' not found", parent=manage_window)
                return

            try:
                monitor_id, input_source = current
            except Exception:
                monitor_id, input_source = 0, "HDMI1"

            edit_win = customtkinter.CTkToplevel(manage_window)
            edit_win.title(f"Edit Favorite - {name}")
            edit_win.transient(manage_window)
            edit_win.grab_set()
            edit_win.resizable(False, False)
            self._center_dialog_on_parent(edit_win, manage_window, 350, 220)

            frm = customtkinter.CTkFrame(edit_win)
            frm.pack(fill="both", expand=True, padx=12, pady=12)

            # Name
            name_label2 = customtkinter.CTkLabel(frm, text="Name:", font=("Arial", 11))
            name_label2.grid(row=0, column=0, sticky="w", pady=(0, 8))
            name_var2 = customtkinter.StringVar(value=name)
            
            # Limit name entry to 20 characters
            def limit_name_length2(*args):
                value = name_var2.get()
                if len(value) > 20:
                    name_var2.set(value[:20])
            name_var2.trace_add('write', limit_name_length2)
            
            name_entry2 = customtkinter.CTkEntry(frm, textvariable=name_var2, height=32)
            name_entry2.grid(row=0, column=1, sticky="ew", pady=(0, 8), padx=(10, 0))

            # Monitor - using helper method
            mon_label2 = customtkinter.CTkLabel(frm, text="Monitor:", font=("Arial", 11))
            mon_label2.grid(row=1, column=0, sticky="w", pady=(0, 8))

            mon_choices = self._get_monitor_choices()
            default_mon_str = next((s for s in mon_choices if s.startswith(str(monitor_id) + ":")), mon_choices[0])

            mon_var2 = customtkinter.StringVar(value=default_mon_str)
            mon_menu2 = customtkinter.CTkOptionMenu(frm, variable=mon_var2, values=mon_choices, height=32)
            mon_menu2.grid(row=1, column=1, sticky="ew", pady=(0, 8), padx=(10, 0))

            # Input - using helper method
            input_label2 = customtkinter.CTkLabel(frm, text="Input:", font=("Arial", 11))
            input_label2.grid(row=2, column=0, sticky="w", pady=(0, 8))

            sel_id_init = self._parse_monitor_selection(default_mon_str)
            inputs_list2 = self._get_inputs_for_monitor(sel_id_init) or ["DP1", "HDMI1", "DP2", "HDMI2"]
            input_var2 = customtkinter.StringVar(value=input_source if input_source in inputs_list2 else (inputs_list2[0] if inputs_list2 else "HDMI1"))
            input_menu2 = customtkinter.CTkOptionMenu(frm, variable=input_var2, values=inputs_list2, height=32)
            input_menu2.grid(row=2, column=1, sticky="ew", pady=(0, 8), padx=(10, 0))

            frm.grid_columnconfigure(1, weight=1)

            def update_input_options2(*args):
                sel_id = self._parse_monitor_selection(mon_var2.get())
                new_inputs = self._get_inputs_for_monitor(sel_id) or ["DP1", "HDMI1", "DP2", "HDMI2"]
                try:
                    input_menu2.configure(values=new_inputs)
                    input_var2.set(new_inputs[0])
                except Exception:
                    pass

            mon_var2.trace_add('write', update_input_options2)

            def save_edit():
                newname = name_var2.get().strip()
                
                # FIX #7: Use validation helper method
                is_valid, error_msg = self._validate_favorite_name(newname, exclude_name=name)
                if not is_valid:
                    messagebox.showerror("Validation Error", error_msg, parent=edit_win)
                    try:
                        name_entry2.focus_set()
                        name_entry2.select_range(0, 'end')
                    except Exception:
                        pass
                    return

                monitor_id_new = self._parse_monitor_selection(mon_var2.get())
                input_new = input_var2.get()

                try:
                    if newname != name and name in self.favorites:
                        del self.favorites[name]
                    self.favorites[newname] = (monitor_id_new, input_new)
                    self.save_favorites()
                    update_favorites_list()
                    self.refresh_favorites_buttons()
                    messagebox.showinfo("Success", f"Favorite '{newname}' saved!", parent=edit_win)
                    edit_win.destroy()
                except Exception as e:
                    logging.error(f"Failed to save edited favorite: {e}")
                    messagebox.showerror("Error", "Failed to save favorite", parent=edit_win)

            btn_frame = customtkinter.CTkFrame(frm, fg_color='transparent')
            btn_frame.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(10, 0))

            save_btn = customtkinter.CTkButton(btn_frame, text="💾 Save", command=save_edit, height=36, width=100, fg_color="#28a745", hover_color="#218838")
            save_btn.pack(side="right", padx=(0, 6))

            cancel_btn = customtkinter.CTkButton(btn_frame, text="Cancel", command=edit_win.destroy, height=36, width=100, fg_color="#dc3545", hover_color="#c82333")
            cancel_btn.pack(side="right", padx=(0, 6))

            # Make the edit dialog a bit larger (but smaller than Manage Favorites)
            edit_win.update_idletasks()
            req_w = max(360, min(440, frm.winfo_reqwidth() + 60))
            req_h = frm.winfo_reqheight() + 40
            edit_win.geometry(f"{req_w}x{req_h}")
        
        # Add new favorite section
        # FIX #6: Refactored to use helper methods, reducing duplicate code
        add_section = customtkinter.CTkFrame(main_frame)
        add_section.pack(fill="x", pady=(0, 0))
        
        add_header = customtkinter.CTkLabel(add_section, text="Add New Favorite:", font=("Arial", 12, "bold"))
        add_header.pack(anchor="w", padx=12, pady=(12, 8))
        
        form_frame = customtkinter.CTkFrame(add_section, fg_color="transparent")
        form_frame.pack(fill="x", padx=12, pady=(0, 12))
        
        # Name input
        name_label = customtkinter.CTkLabel(form_frame, text="Name:", font=("Arial", 11))
        name_label.grid(row=0, column=0, sticky="w", pady=(0, 8))
        
        name_entry = customtkinter.CTkEntry(form_frame, height=32, placeholder_text="Your Setup Name")
        name_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8), padx=(10, 0))
        
        # Monitor selection - using helper method
        mon_label = customtkinter.CTkLabel(form_frame, text="Monitor:", font=("Arial", 11))
        mon_label.grid(row=1, column=0, sticky="w", pady=(0, 8))
        
        mon_choices = self._get_monitor_choices()
        
        mon_var = customtkinter.StringVar(value=mon_choices[0])
        mon_menu = customtkinter.CTkOptionMenu(form_frame, variable=mon_var, values=mon_choices, height=32)
        mon_menu.grid(row=1, column=1, sticky="ew", pady=(0, 8), padx=(10, 0))
        
        # Input selection - using helper method
        input_label = customtkinter.CTkLabel(form_frame, text="Input:", font=("Arial", 11))
        input_label.grid(row=2, column=0, sticky="w", pady=(0, 8))
        
        initial_monitor_id = self._parse_monitor_selection(mon_choices[0])
        initial_inputs = self._get_inputs_for_monitor(initial_monitor_id) or ["HDMI1", "DP1"]
        input_var = customtkinter.StringVar(value=initial_inputs[0] if initial_inputs else "HDMI1")
        input_menu = customtkinter.CTkOptionMenu(form_frame, variable=input_var, values=initial_inputs, height=32)
        input_menu.grid(row=2, column=1, sticky="ew", pady=(0, 8), padx=(10, 0))
        
        form_frame.grid_columnconfigure(1, weight=1)
        
        def update_input_options(*args):
            sel_id = self._parse_monitor_selection(mon_var.get())
            inputs_for_sel = self._get_inputs_for_monitor(sel_id) or ["DP1", "HDMI1", "DP2", "HDMI2"]
            input_menu.configure(values=inputs_for_sel)
            input_var.set(inputs_for_sel[0])
        
        mon_var.trace_add('write', update_input_options)
        
        def add_fav():
            name = name_entry.get().strip()
            
            # FIX #7: Use validation helper method
            is_valid, error_msg = self._validate_favorite_name(name)
            if not is_valid:
                messagebox.showerror("Validation Error", error_msg, parent=manage_window)
                try:
                    name_entry.focus_set()
                    name_entry.select_range(0, 'end')
                except Exception:
                    pass
                return
            
            monitor_id = self._parse_monitor_selection(mon_var.get())
            input_source = input_var.get()
            
            if self.add_favorite(name, monitor_id, input_source):
                update_favorites_list()
                self.refresh_favorites_buttons()
                name_entry.delete(0, 'end')
                messagebox.showinfo("Success", f"Favorite '{name}' added!", parent=manage_window)
            else:
                messagebox.showerror("Error", "Failed to add favorite", parent=manage_window)
        
        add_btn = customtkinter.CTkButton(form_frame, text="➕ Add Favorite", command=add_fav, height=36, font=("Arial", 12, "bold"), fg_color="#28a745", hover_color="#218838")
        add_btn.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        
        update_favorites_list()

    def show_shortcuts_editor(self):
        """Show shortcuts editor dialog"""
        editor_window = customtkinter.CTkToplevel(self)
        # Track this editor window so it can be disabled during refresh
        self.editor_window = editor_window
        editor_window.title("Keyboard Shortcuts")
        editor_window.resizable(False, False)
        editor_window.transient(self)
        editor_window.grab_set()
        self._center_dialog_on_parent(editor_window, self, 520, 600)
        editor_window.bind('<Destroy>', lambda e: setattr(self, 'editor_window', None))        
        main_frame = customtkinter.CTkFrame(editor_window)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        title = customtkinter.CTkLabel(main_frame, text="⌨️ Keyboard Shortcuts", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 10))
        
        # Add prominent disclaimer about global hotkeys
        disclaimer_frame = customtkinter.CTkFrame(main_frame, fg_color=("#E3F2FD", "#1E3A5F"))
        disclaimer_frame.pack(fill="x", pady=(0, 15), padx=5)
        
        disclaimer_icon = customtkinter.CTkLabel(
            disclaimer_frame,
            text="💡",
            font=("Arial", 16)
        )
        disclaimer_icon.pack(side="left", padx=(10, 5), pady=8)
        
        # Ensure disclaimer text is readable in dark mode
        disc_color = "#000000" if customtkinter.get_appearance_mode() == "Light" else "#EDEDED"
        disclaimer_text = customtkinter.CTkLabel(
            disclaimer_frame,
            text="Global hotkeys work even when the app is minimized or in the background.\nPress Ctrl+Shift+H anywhere to show shortcuts help.",
            font=("Arial", 11, "bold"),
            justify="left",
            text_color=disc_color,
            wraplength=460
        )
        disclaimer_text.pack(side="left", padx=(5, 10), pady=8)

        # Shortcuts list section
        shortcuts_section = customtkinter.CTkFrame(main_frame)
        shortcuts_section.pack(fill="both", expand=True, pady=(0, 15))
        
        shortcuts_header = customtkinter.CTkLabel(shortcuts_section, text="Current Shortcuts:", font=("Arial", 13, "bold"))
        shortcuts_header.pack(anchor="w", padx=12, pady=(12, 8))
        
        shortcuts_frame = customtkinter.CTkScrollableFrame(shortcuts_section, height=320)
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
                    font=("Arial", 12),
                    wraplength=420
                )
                label.pack(side="left", padx=8, pady=6) 

                btn_frame = customtkinter.CTkFrame(shortcut_frame, fg_color="transparent")
                btn_frame.pack(side="right", padx=8)

                edit_btn = customtkinter.CTkButton(
                    btn_frame,
                    text="Edit",
                    width=70,
                    height=32,
                    font=("Arial", 11),
                    command=lambda s=shortcut: edit_shortcut(s)
                )
                edit_btn.pack(side="left", padx=4)

                delete_btn = customtkinter.CTkButton(
                    btn_frame,
                    text="Delete",
                    width=70,
                    height=32,
                    font=("Arial", 11),
                    command=lambda s=shortcut: delete_shortcut(s),
                    fg_color=("#D32F2F", "#C62828"),
                    hover_color=("#C62828", "#B71C1C")
                )
                delete_btn.pack(side="left", padx=4)

            if shown == 0:
                notice = customtkinter.CTkLabel(shortcuts_frame, text="No shortcuts for currently connected monitors.", text_color="gray")
                notice.pack(pady=20)

        def record_shortcut(callback):
            dialog = customtkinter.CTkToplevel(editor_window)
            dialog.title("Record Shortcut")
            dialog.transient(editor_window)
            dialog.grab_set()
            self._center_dialog_on_parent(dialog, editor_window, 350, 150)
            set_dark_title_bar(dialog)  # Apply dark title bar if in dark mode
            
            label = customtkinter.CTkLabel(dialog, text="Press the desired key combination...", font=("Arial", 12))
            label.pack(pady=30)
            
            recorded_keys = []
            
            # FIX #3: Track the keyboard hook so we can unhook it when dialog closes
            hook_handle = [None]  # Use list to allow modification in nested function
            
            # Map of characters to their scan codes for number keys
            char_to_key = {
                '@': '2', '!': '1', '#': '3', '$': '4', '%': '5',
                '^': '6', '&': '7', '*': '8', '(': '9', ')': '0'
            }
            
            def cleanup_hook():
                """Remove the keyboard hook to prevent memory leaks"""
                if hook_handle[0] is not None:
                    try:
                        keyboard.unhook(hook_handle[0])
                    except Exception:
                        pass
                    hook_handle[0] = None
            
            def on_key(event):
                if event.name not in recorded_keys and event.name not in ['ctrl', 'alt', 'shift']:
                    recorded_keys.extend(k for k in ['ctrl', 'alt', 'shift'] if keyboard.is_pressed(k))
                    
                    # Map shifted characters back to their base keys
                    key_name = char_to_key.get(event.name, event.name)
                    recorded_keys.append(key_name)
                    
                    shortcut = '+'.join(recorded_keys)
                    label.configure(text=f"Recorded: {shortcut}\n\nPress ENTER to confirm or ESC to cancel")
                    
                    if event.name == 'enter':
                        cleanup_hook()
                        dialog.destroy()
                        callback('+'.join(recorded_keys[:-1]))
                    elif event.name == 'esc':
                        cleanup_hook()
                        dialog.destroy()
            
            hook_handle[0] = keyboard.on_press(on_key)
            
            # FIX #3: Also cleanup if user closes dialog via window X button
            dialog.protocol("WM_DELETE_WINDOW", lambda: (cleanup_hook(), dialog.destroy()))
            
        def add_new_shortcut():
            def on_shortcut(shortcut):
                if shortcut:
                    select_dialog = customtkinter.CTkToplevel(editor_window)
                    select_dialog.title("Configure Shortcut")
                    select_dialog.transient(editor_window)
                    select_dialog.grab_set()
                    self._center_dialog_on_parent(select_dialog, editor_window, 400, 280)
                    set_dark_title_bar(select_dialog)  # Apply dark title bar if in dark mode

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
                                try:
                                    messagebox.showinfo("Success", f"Shortcut '{shortcut}' added!", parent=select_dialog)
                                except Exception:
                                    pass
                                select_dialog.destroy()
                            else:
                                messagebox.showerror("Error", "Failed to save shortcut", parent=select_dialog)
                        except ValueError:
                            messagebox.showerror("Error", "Invalid monitor selection", parent=select_dialog)

                    save_btn = customtkinter.CTkButton(frame, text="Save Shortcut", command=save, height=36, font=("Arial", 12, "bold"), fg_color="#28a745", hover_color="#218838")
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
            """Edit an existing shortcut - allows changing both the key and the monitor/input"""
            current_monitor_id, current_input = self.shortcuts.get(shortcut, (0, "HDMI1"))
            
            edit_dialog = customtkinter.CTkToplevel(editor_window)
            edit_dialog.title("Edit Shortcut")
            edit_dialog.transient(editor_window)
            edit_dialog.grab_set()
            self._center_dialog_on_parent(edit_dialog, editor_window, 400, 350)
            set_dark_title_bar(edit_dialog)
            
            frame = customtkinter.CTkFrame(edit_dialog)
            frame.pack(fill="both", expand=True, padx=20, pady=20)
            
            # Current shortcut display
            shortcut_var = customtkinter.StringVar(value=shortcut)
            shortcut_label = customtkinter.CTkLabel(frame, text="Shortcut Key:", font=("Arial", 11))
            shortcut_label.pack(anchor="w", pady=(0, 5))
            
            shortcut_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
            shortcut_frame.pack(fill="x", pady=(0, 15))
            
            shortcut_display = customtkinter.CTkLabel(shortcut_frame, textvariable=shortcut_var, font=("Arial", 13, "bold"))
            shortcut_display.pack(side="left", padx=(0, 10))
            
            def change_key():
                def on_new_key(new_key):
                    if new_key:
                        shortcut_var.set(new_key)
                record_shortcut(on_new_key)
            
            change_key_btn = customtkinter.CTkButton(shortcut_frame, text="Change Key", command=change_key, width=100, height=28)
            change_key_btn.pack(side="left")
            
            # Monitor selection
            monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else []
            mon_choices = [f"{m.get('id')}: {m.get('display_name')}" for m in monitors_list] if monitors_list else ["0"]
            
            # Find the current monitor choice
            current_mon_choice = mon_choices[0]
            for choice in mon_choices:
                if choice.startswith(f"{current_monitor_id}:"):
                    current_mon_choice = choice
                    break
            
            mon_label = customtkinter.CTkLabel(frame, text="Select Monitor:", font=("Arial", 11))
            mon_label.pack(anchor="w", pady=(0, 5))
            
            mon_var = customtkinter.StringVar(value=current_mon_choice)
            mon_menu = customtkinter.CTkOptionMenu(frame, variable=mon_var, values=mon_choices, height=32)
            mon_menu.pack(fill="x", pady=(0, 15))
            
            # Input selection
            input_label = customtkinter.CTkLabel(frame, text="Select Input:", font=("Arial", 11))
            input_label.pack(anchor="w", pady=(0, 5))
            
            initial_inputs = []
            for mon in monitors_list:
                if mon.get('id') == current_monitor_id:
                    initial_inputs = mon.get('inputs', [])
                    break
            if not initial_inputs:
                initial_inputs = ["DP1", "HDMI1", "DP2", "HDMI2"]
            
            input_var = customtkinter.StringVar(value=current_input if current_input in initial_inputs else initial_inputs[0])
            input_menu = customtkinter.CTkOptionMenu(frame, variable=input_var, values=initial_inputs, height=32)
            input_menu.pack(fill="x", pady=(0, 20))
            
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
                # Keep current input if it exists in new list, otherwise use first
                if input_var.get() not in inputs_for_sel:
                    input_var.set(inputs_for_sel[0])
            
            mon_var.trace_add('write', update_input_options)
            
            def save():
                try:
                    new_shortcut = shortcut_var.get()
                    sel = mon_var.get()
                    monitor_id = int(sel.split(':', 1)[0].strip()) if ':' in sel else int(sel)
                    input_source = input_var.get()
                    
                    # Remove old shortcut if key changed
                    if new_shortcut != shortcut:
                        self.shortcuts.pop(shortcut, None)
                    
                    # Save new/updated shortcut
                    self.shortcuts[new_shortcut] = (monitor_id, input_source)
                    self.save_shortcuts()
                    
                    try:
                        keyboard.clear_all_hotkeys()
                    except Exception:
                        pass
                    
                    self.setup_global_hotkeys()
                    update_shortcuts_list()
                    
                    try:
                        messagebox.showinfo("Success", f"Shortcut '{new_shortcut}' saved!", parent=edit_dialog)
                    except Exception:
                        pass
                    edit_dialog.destroy()
                except ValueError:
                    messagebox.showerror("Error", "Invalid monitor selection", parent=edit_dialog)
            
            save_btn = customtkinter.CTkButton(frame, text="Save Changes", command=save, height=36, font=("Arial", 12, "bold"), fg_color="#28a745", hover_color="#218838")
            save_btn.pack(fill="x")

            
        def delete_shortcut(shortcut):
            try:
                try:
                    confirm = messagebox.askyesno("Confirm Delete", f"Delete shortcut '{shortcut}'?", parent=editor_window)
                except Exception:
                    confirm = True

                if not confirm:
                    return

                self.shortcuts.pop(shortcut)
                self.save_shortcuts()
                try:
                    keyboard.clear_all_hotkeys()
                except Exception:
                    pass
                self.setup_global_hotkeys()
                update_shortcuts_list()
                try:
                    messagebox.showinfo("Success", f"Shortcut '{shortcut}' deleted!", parent=editor_window)
                except Exception:
                    pass
            except Exception as e:
                logging.error(f"Failed to delete shortcut {shortcut}: {e}")
        
        # Buttons section
        buttons_frame = customtkinter.CTkFrame(main_frame, fg_color="transparent")
        buttons_frame.pack(fill="x")
        
        add_button = customtkinter.CTkButton(buttons_frame, text="➕ Add New Shortcut", command=add_new_shortcut, height=36, font=("Arial", 12, "bold"), fg_color="#28a745", hover_color="#218838")
        add_button.pack(fill="x")
        
        update_shortcuts_list()

    def show_shortcuts_help(self):
        """Show shortcuts help dialog"""
        help_window = customtkinter.CTkToplevel(self)
        help_window.title("Keyboard Shortcuts Help")
        help_window.transient(self)
        help_window.grab_set()
        self._center_dialog_on_parent(help_window, self, 450, 400)
        
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

def get_input_name(code):
    """Convert input code to readable name"""
    # Standard InputSource enum mapping
    standard_inputs = {
        0: "NO INPUT",
        1: "VGA1", #Change ANALOG1/VGA to VGA1 
        2: "VGA2", #Change ANALOG2 to VGA2
        3: "DVI1",
        4: "DVI2",
        5: "COMPOSITE1",
        6: "COMPOSITE2",
        7: "SVIDEO1",
        8: "SVIDEO2",
        9: "TUNER1",
        10: "TUNER2",
        11: "TUNER3",
        12: "COMPONENT1",
        13: "COMPONENT2",
        14: "COMPONENT3",
        15: "DP1",
        16: "DP2",
        17: "HDMI1",
        18: "HDMI2",
        VCP_INPUT_THUNDERBOLT: "THUNDERBOLT",
        VCP_INPUT_USB_C: "USB-C"
    }
    
    return standard_inputs.get(code, f"UNKNOWN CODE {code}")

def cli_switch_input(monitor_index, input_name):
    """Switch input via command line interface"""
    # FIX #2: Get monitors fresh for CLI mode (not using global variable)
    monitors = get_monitors()
    
    try:
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