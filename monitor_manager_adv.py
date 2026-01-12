"""
================================================================================
MONITOR INPUT SWITCHER - Advanced Monitor Management Application
================================================================================

This application provides a graphical user interface (GUI) for switching input 
sources on external monitors using DDC/CI (Display Data Channel Command Interface) 
protocol. It allows users to control multiple monitors, save favorite configurations,
and set up global keyboard shortcuts for quick switching.

MAIN FEATURES:
--------------
1. Monitor Detection: Automatically detects connected external monitors using DDC/CI
2. Input Switching: Switch between various input sources (HDMI, DisplayPort, USB-C, etc.)
3. Favorites System: Save and quickly apply frequently used monitor configurations
4. Global Hotkeys: Set up keyboard shortcuts that work system-wide
5. System Tray: Optionally minimize to system tray for background operation
6. Theme Support: Dark, Light, and System (follows Windows theme) modes
7. DPI Awareness: Automatically scales UI based on monitor DPI settings
8. CLI Mode: Command-line interface for scripting and automation

TECHNICAL ARCHITECTURE:
----------------------
- Uses CustomTkinter for modern-looking GUI widgets
- monitorcontrol library for DDC/CI communication with monitors
- pystray for system tray functionality
- keyboard library for global hotkey registration
- Threading for non-blocking monitor detection

AUTHOR: LuqmanHakimAmiruddin@PDC
VERSION: 3.1 (Advanced)
================================================================================
"""

# ==============================================================================
# IMPORTS
# ==============================================================================

# GUI Framework - CustomTkinter provides modern-looking widgets on top of Tkinter
import customtkinter

# Monitor Control - DDC/CI communication library for controlling monitor settings
# get_monitors: Returns list of connected DDC/CI capable monitors
# InputSource: Enum containing standard input source codes (HDMI1, DP1, etc.)
from monitorcontrol import get_monitors, InputSource

# Standard Library Imports
import platform      # OS detection for Windows-specific features
import logging       # Application logging for debugging and error tracking
import threading     # Background thread for non-blocking monitor detection
import os           # File system operations
import sys          # System-specific parameters (for PyInstaller resource paths)
import shutil       # High-level file operations (for migrating config files)
from pathlib import Path  # Modern path handling
import json         # JSON serialization for config files (shortcuts, favorites, settings)
from tkinter import messagebox  # Native dialog boxes for alerts and confirmations

# Keyboard Hook Library - For registering global system-wide keyboard shortcuts
import keyboard

# Screen Information - For getting monitor dimensions and positions
from screeninfo import get_monitors as get_screen_info

# System Tray Support - For creating taskbar tray icon
# FIX #4: Removed unused top-level 'import winreg' - it's imported locally in read_edid() where needed
from pystray import Icon, Menu, MenuItem

# Image Processing - For creating system tray icon image
from PIL import Image, ImageDraw

# Windows API Access - For setting dark title bar on Windows 10/11
import ctypes

# ==============================================================================
# GLOBAL CONFIGURATION CONSTANTS
# ==============================================================================

# Available themes for customtkinter appearance mode
# "system" automatically follows Windows light/dark mode setting
AVAILABLE_THEMES = ["dark", "light", "system"]

# ==============================================================================
# WINDOWS TITLE BAR CUSTOMIZATION
# ==============================================================================

def set_dark_title_bar(window):
    """
    Apply dark title bar styling to a window on Windows 10/11.
    
    This function uses the Windows Desktop Window Manager (DWM) API to set
    the DWMWA_USE_IMMERSIVE_DARK_MODE attribute, which enables the dark
    theme for the window's title bar and borders.
    
    Args:
        window: A Tkinter or CustomTkinter window/toplevel object
        
    Note:
        - Only works on Windows 10 version 1809+ and Windows 11
        - Silently fails on older Windows versions or non-Windows platforms
        - Only applies dark styling when CustomTkinter is in dark mode
    """
    # Skip if not running on Windows
    if platform.system() != 'Windows':
        return
    try:
        # Only apply dark title bar when the app is in dark mode
        if customtkinter.get_appearance_mode().lower() == "dark":
            window.update()  # Ensure window handle is created before accessing it
            
            # Get the Win32 window handle (HWND) from the Tkinter window
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 10 1809+/Windows 11)
            # This attribute enables dark mode for the window chrome (title bar, borders)
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            value = ctypes.c_int(1)  # 1 = enable dark mode
            
            # Call DwmSetWindowAttribute to apply the dark mode setting
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass  # Silently fail on older Windows versions that don't support this attribute

# ==============================================================================
# WINDOWS-SPECIFIC IMPORTS
# ==============================================================================

# Import WMI (Windows Management Instrumentation) only on Windows
# WMI is used for querying detailed monitor information like PnP Device IDs
if platform.system() == 'Windows':
    import wmi        # Windows Management Instrumentation - for hardware queries
    import pythoncom  # COM library initialization - required for WMI in threads

# ==============================================================================
# CONFIGURATION DIRECTORY MANAGEMENT
# ==============================================================================

def get_user_config_dir():
    """
    Determine the appropriate directory for storing user configuration files.
    
    This function returns a platform-appropriate directory for storing
    persistent user data like shortcuts, favorites, and settings. The
    directory is created if it doesn't exist.
    
    Returns:
        str: Absolute path to the configuration directory
        
    Platform Locations:
        - Windows: %APPDATA%\\monitor_manager (e.g., C:\\Users\\Name\\AppData\\Roaming\\monitor_manager)
        - Linux/Mac: ~/.config/monitor_manager
        
    Fallback:
        Returns current working directory if platform detection fails
    """
    app_name = 'monitor_manager'
    home = Path.home()
    try:
        if platform.system() == 'Windows':
            # Use Windows AppData/Roaming for user-specific persistent data
            appdata = os.getenv('APPDATA')
            if not appdata:
                # Fallback if APPDATA environment variable is not set
                appdata = str(home / 'AppData' / 'Roaming')
            return os.path.join(appdata, app_name)
        else:
            # Unix-like systems use XDG convention (~/.config/)
            return os.path.join(str(home), '.config', app_name)
    except Exception:
        # If all else fails, use the current directory
        return os.path.abspath('.')

# ==============================================================================
# LOGGING CONFIGURATION
# ==============================================================================

# Initialize configuration directory for storing logs and settings
config_dir = get_user_config_dir()
try:
    # Create the config directory if it doesn't exist (including parent directories)
    os.makedirs(config_dir, exist_ok=True)
except Exception:
    pass  # Directory creation failures are non-fatal

# Configure logging to write to a file in the config directory
# Log format includes timestamp, log level, and message for debugging
log_file = os.path.join(config_dir, 'monitor_manager.log')
logging.basicConfig(
    filename=log_file, 
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ==============================================================================
# MONITOR MANUFACTURER IDENTIFICATION TABLES
# ==============================================================================

# PnP (Plug and Play) ID to Manufacturer Name mapping
# These 3-letter codes are defined in the VESA EDID standard and identify manufacturers
# Used to display human-readable brand names in the monitor selection dropdown
PNP_IDS = {
    "AAC": "Acer", "ACR": "Acer", "AOC": "AOC", "AUO": "AU Optronics",
    "BNQ": "BenQ", "CMO": "Chi Mei", "DEL": "Dell", "HEI": "Hisense",
    "HPN": "HP", "HSD": "Hisense", "HWP": "HP", "IVM": "Iiyama",
    "LGD": "LG Display", "LPL": "LG Philips", "NEC": "NEC", "SAM": "Samsung",
    "SEC": "Samsung", "SNY": "Sony", "TCL": "TCL", "TOS": "Toshiba",
    "TPV": "TPV", "VSC": "ViewSonic", "GGL": "Google", "MSI": "MSI",
    "GIG": "Gigabyte", "RAZ": "Razer",
}

# ==============================================================================
# DDC/CI INPUT SOURCE CODES
# ==============================================================================

# USB-C Display Detection:
# USB-C ports with DisplayPort Alt Mode are detected via DDC/CI VCP codes.
# The standard InputSource enum covers common inputs: HDMI, DP, DVI, VGA, etc.
# Non-standard codes are displayed as INPUT_<code> for debugging purposes.

# FIX #5: VCP Input Source Codes (DDC/CI standard) - replaces magic numbers
# These constants define VCP (Virtual Control Panel) codes for input sources
# that aren't included in the standard InputSource enum
VCP_INPUT_THUNDERBOLT = 26  # Code 0x1A - Thunderbolt (uses USB-C connector with DP protocol)
VCP_INPUT_USB_C = 27        # Code 0x1B - USB-C with DisplayPort Alt Mode

# Model prefix to brand name mapping
# Used as a fallback when PnP ID lookup fails
# Maps common monitor model prefixes to their manufacturer
MODEL_BRAND_MAP = {
    # ASUS monitor model prefixes
    "PA": "ASUS", "PG": "ASUS", "VG": "ASUS", "MG": "ASUS", "ROG": "ASUS", 
    "TUF": "ASUS", "BE": "ASUS",
    # Dell/Alienware
    "AW": "Alienware", 
    "U24": "Dell", "U27": "Dell", "U34": "Dell", "P24": "Dell", "P27": "Dell", 
    "S24": "Dell", "S27": "Dell", "E24": "Dell", "E27": "Dell",
    # LG monitor model prefixes
    "LG": "LG", "MP": "LG", "GP": "LG", "OLED": "LG", "GL": "LG", 
    "GN": "LG", "UK": "LG", "UM": "LG",
    # Samsung monitor model prefixes
    "C24G": "Samsung", "C27G": "Samsung", "C32G": "Samsung", "ODYSSEY": "Samsung", 
    "LS": "Samsung", "F24": "Samsung", "F27": "Samsung",
    # AOC monitor model prefixes
    "27G": "AOC", "24G": "AOC", "22": "AOC", "Q27": "AOC", "CQ": "AOC",
    "C24": "AOC", "C27": "AOC", "C32": "AOC", "AG": "AOC", "AGON": "AOC",
    # ViewSonic
    "VX": "ViewSonic", "VA": "ViewSonic", "VG": "ViewSonic",
    # BenQ
    "XL": "BenQ", "EX": "BenQ", "PD": "BenQ", "EW": "BenQ", "ZOWIE": "BenQ", "GW": "BenQ",
    # Acer
    "XV": "Acer", "XF": "Acer", "KG": "Acer", "CB": "Acer", "XB": "Acer",
    "NITRO": "Acer", "PREDATOR": "Acer",
    # MSI
    "MAG": "MSI", "MPG": "MSI", "OPTIX": "MSI", "MEG": "MSI",
    # Gigabyte
    "FI": "Gigabyte", "M27": "Gigabyte", "M32": "Gigabyte", "G27F": "Gigabyte", "AORUS": "Gigabyte",
    # HP
    "OMEN": "HP", "X27": "HP", "Z27": "HP", "PAVILION": "HP",
    # Philips
    "BDM": "Philips", "PHL": "Philips", "PHI": "Philips"
}

# FIX #2: Removed static 'monitors = get_monitors()' that only ran at module load.
# Monitors are now refreshed dynamically in get_all_monitor_data() to detect
# newly connected/disconnected monitors during runtime.

# ==============================================================================
# RESPONSIVE UI SCALING SYSTEM
# ==============================================================================

# Base values designed for 1080p (1920x1080) at 96 DPI (100% Windows scaling)
# All UI dimensions are scaled relative to these baseline values
BASE_SCREEN_HEIGHT = 1080  # Reference resolution height
BASE_DPI = 96              # Standard DPI (100% scaling on Windows)


class UIScaler:
    """
    Responsive UI scaling calculator for multi-DPI display support.
    
    This class calculates appropriate scaling factors based on the current
    display's resolution and DPI settings. It ensures the UI looks consistent
    and properly sized across different monitors with varying DPI settings.
    
    The scaling is calculated relative to a 1080p/96 DPI baseline, which is
    the most common configuration and serves as the "1.0x" reference point.
    
    Attributes:
        root: The root Tkinter window used to query display metrics
        scale: Combined scaling factor (0.75 - 2.0 range)
        resolution_scale: Scale factor based on screen resolution
        dpi_scale: Scale factor based on screen DPI
        
    Usage Example:
        scaler = UIScaler(root_window)
        button_height = scaler.size(40)  # Returns scaled button height
        font = scaler.font("Arial", 12, "bold")  # Returns scaled font tuple
    """
    
    def __init__(self, root):
        """
        Initialize the UI scaler with the root window.
        
        Args:
            root: The main Tkinter/CustomTkinter window object
        """
        self.root = root
        self._last_dpi = None  # Track DPI for change detection
        self._calculate_scale_factors()
    
    def _calculate_scale_factors(self):
        """
        Calculate scaling factors based on current screen metrics.
        
        This method queries the screen height and DPI from Tkinter and
        calculates appropriate scale factors. The final scale is a weighted
        combination of DPI (70%) and resolution (30%) factors, clamped to
        a reasonable range of 0.75x to 2.0x.
        """
        try:
            # Get screen dimensions from Tkinter
            screen_height = self.root.winfo_screenheight()
            
            # Get DPI (pixels per inch) - reflects current monitor's DPI setting
            # winfo_fpixels('1i') returns how many pixels make up 1 inch
            dpi = self.root.winfo_fpixels('1i')
            self._last_dpi = dpi
            
            # Calculate individual scale factors
            # Resolution scale: ratio of current height to 1080p baseline
            self.resolution_scale = screen_height / BASE_SCREEN_HEIGHT
            
            # DPI scale: ratio of current DPI to standard 96 DPI
            self.dpi_scale = dpi / BASE_DPI
            
            # Combined scale factor (weighted average)
            # DPI is weighted more heavily (70%) as it's the primary indicator
            # of user's preferred UI size
            self.scale = (self.dpi_scale * 0.7) + (self.resolution_scale * 0.3)
            
            # Clamp scale to reasonable bounds to prevent extreme sizes
            # 0.75x minimum prevents UI from becoming too small to use
            # 2.0x maximum prevents excessive enlargement
            self.scale = max(0.75, min(2.0, self.scale))
            
        except Exception:
            # Fallback to 1.0 scale (no scaling) if detection fails
            self.scale = 1.0
            self.resolution_scale = 1.0
            self.dpi_scale = 1.0
            self._last_dpi = BASE_DPI
    
    def check_dpi_change(self):
        """
        Check if DPI has changed (e.g., window moved to different monitor).
        
        This method is called when the window moves to detect if it has
        been moved to a monitor with different DPI settings. If the DPI
        has changed significantly (more than 1 unit difference), the
        scale factors are recalculated.
        
        Returns:
            bool: True if DPI changed and scaling was recalculated, False otherwise
        """
        try:
            current_dpi = self.root.winfo_fpixels('1i')
            # Check for significant DPI change (more than 1 unit)
            if self._last_dpi is not None and abs(current_dpi - self._last_dpi) > 1:
                self._calculate_scale_factors()
                return True
        except Exception:
            pass
        return False
    
    def size(self, base_value):
        """
        Scale a dimension value (width, height, padding, margin, etc.).
        
        Args:
            base_value: The base size value at 1080p/96 DPI
            
        Returns:
            int: Scaled size value appropriate for current display
        """
        return int(base_value * self.scale)
    
    def font_size(self, base_size):
        """
        Scale a font size with slightly conservative scaling.
        
        Fonts are scaled less aggressively than dimensions to maintain
        readability. Uses 80% of the scale delta to prevent fonts from
        becoming too large or too small.
        
        Args:
            base_size: The base font size at 1080p/96 DPI
            
        Returns:
            int: Scaled font size
        """
        # Apply 80% of the scale change for fonts (more conservative)
        font_scale = (self.scale - 1.0) * 0.8 + 1.0
        return int(base_size * font_scale)
    
    def font(self, family, size, weight=""):
        """
        Create a scaled font tuple for use with Tkinter widgets.
        
        Args:
            family: Font family name (e.g., "Arial", "Helvetica")
            size: Base font size at 1080p/96 DPI
            weight: Optional font weight (e.g., "bold", "italic")
            
        Returns:
            tuple: Font tuple in format (family, size) or (family, size, weight)
        """
        scaled_size = self.font_size(size)
        if weight:
            return (family, scaled_size, weight)
        return (family, scaled_size)
    
    def window_size(self, base_width, base_height):
        """
        Calculate scaled window dimensions as a geometry string.
        
        Args:
            base_width: Base window width at 1080p/96 DPI
            base_height: Base window height at 1080p/96 DPI
            
        Returns:
            str: Tkinter geometry string in format "WIDTHxHEIGHT"
        """
        width = self.size(base_width)
        height = self.size(base_height)
        return f"{width}x{height}"


# ==============================================================================
# PYINSTALLER RESOURCE PATH HELPER
# ==============================================================================

def resource_path(relative_path):
    """
    Get the absolute path to a resource file, works for dev and PyInstaller.
    
    When the application is packaged with PyInstaller, resources are extracted
    to a temporary folder accessible via sys._MEIPASS. In development mode,
    resources are accessed from the current directory.
    
    Args:
        relative_path: Path to the resource relative to the application root
        
    Returns:
        str: Absolute path to the resource file
        
    Example:
        icon_path = resource_path('monitor_manager_icon.ico')
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # Running in development mode - use current directory
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# ==============================================================================
# MAIN APPLICATION CLASS
# ==============================================================================

class App(customtkinter.CTk):
    """
    Main application window for the Monitor Input Switcher.
    
    This class creates and manages the main GUI window, including:
    - Monitor detection and selection
    - Input source switching
    - Favorites management
    - Global keyboard shortcuts
    - System tray integration
    - Theme and settings management
    
    The application uses CustomTkinter for a modern-looking interface and
    supports both GUI and CLI modes of operation.
    
    Inheritance:
        Extends customtkinter.CTk which is an enhanced version of tkinter.Tk
        with built-in theming and modern widget styling.
    """
    
    def __init__(self):
        """
        Initialize the main application window and all its components.
        
        This method sets up:
        1. UI scaling for different DPI displays
        2. Window properties (title, size, position)
        3. System tray integration
        4. Configuration file paths
        5. Theme and settings loading
        6. Global hotkey registration
        7. All UI widgets and layouts
        """
        super().__init__()

        # ----------------------------------------------------------------------
        # UI SCALING INITIALIZATION
        # ----------------------------------------------------------------------
        # Initialize UI scaler for responsive sizing across different DPI displays
        self.ui = UIScaler(self)
        
        # Apply CustomTkinter's built-in scaling for all widgets
        # This ensures consistent sizing across different DPI displays
        customtkinter.set_widget_scaling(self.ui.scale)
        customtkinter.set_window_scaling(self.ui.scale)
        
        # Track last known window position for DPI change detection
        # Used to detect when window moves to a different monitor
        self._last_x = 0
        self._last_y = 0
        self._dpi_check_scheduled = False  # Debounce flag for DPI checks

        # ----------------------------------------------------------------------
        # WINDOW CONFIGURATION
        # ----------------------------------------------------------------------
        self.title("Monitor Manager")
        self.geometry(self.ui.window_size(520, 540))
        self.resizable(True, True)  # Allow window resizing for accessibility
        
        # Position window on an active display (one showing PC content)
        # This handles the case where primary display is connected but showing another input
        self._position_on_active_display()
        
        # Set window icon (if available)
        try:
            self.iconbitmap(resource_path('monitor_manager_icon.ico'))
        except:
            pass  # Icon not found - use default
        
        # ----------------------------------------------------------------------
        # SYSTEM TRAY SETUP
        # ----------------------------------------------------------------------
        self.tray_icon = None        # pystray Icon object (created when minimizing to tray)
        self.is_quitting = False     # Flag to distinguish close vs minimize to tray
        
        # Easter egg click counter (hidden feature)
        self._easter_egg_clicks = 0
        self._easter_egg_last_click = 0
        
        # FIX #2: Instance-level monitors list (refreshed dynamically)
        # Previously was a module-level variable that only updated at startup
        self.monitors = []
        
        # Override window close behavior and minimize behavior
        # Default behavior is set in update_tray_behavior() based on settings
        self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        self.bind("<Unmap>", self.on_minimize)
        
        # Bind Configure event to detect when window moves (for DPI change detection)
        self.bind("<Configure>", self._on_window_configure)

        # ----------------------------------------------------------------------
        # CONFIGURATION FILE PATHS
        # ----------------------------------------------------------------------
        config_dir = get_user_config_dir()
        try:
            os.makedirs(config_dir, exist_ok=True)
        except Exception:
            pass

        # JSON files for persistent storage
        self.shortcuts_file = os.path.join(config_dir, 'custom_shortcuts.json')  # Keyboard shortcuts
        self.favorites_file = os.path.join(config_dir, 'favorites.json')          # Saved favorites
        self.settings_file = os.path.join(config_dir, 'settings.json')            # App settings

        # Migrate old shortcuts file from application directory to user config directory
        # This ensures settings persist across application updates
        old_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'custom_shortcuts.json')
        try:
            if os.path.exists(old_path) and not os.path.exists(self.shortcuts_file):
                shutil.copy2(old_path, self.shortcuts_file)
                logging.info(f"Migrated shortcuts file from {old_path} to {self.shortcuts_file}")
        except Exception as e:
            logging.debug(f"Could not migrate old shortcuts file: {e}")
        
        # ----------------------------------------------------------------------
        # LOAD SAVED DATA
        # ----------------------------------------------------------------------
        self.shortcuts = self.load_shortcuts() or {}   # Dict: shortcut_key -> (monitor_id, input_source)
        self.favorites = self.load_favorites() or {}   # Dict: name -> (monitor_id, input_source)
        
        # Default window behavior is normal Windows behavior (no system tray)
        # tray_on values: "none", "close", "minimize", "both"
        self.settings = self.load_settings() or {"theme": "system", "tray_on": "none"}
        self.apply_theme()  # Apply saved theme setting
        
        # Apply tray behavior based on settings
        self.update_tray_behavior()
        
        # Register global keyboard shortcuts
        self.setup_global_hotkeys()

        # ==================================================================
        # MAIN UI LAYOUT - HEADER SECTION
        # ==================================================================
        
        # Main container holds all UI elements with consistent padding
        main_container = customtkinter.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=self.ui.size(15), pady=self.ui.size(10))

        # Header bar with title and action buttons
        header = customtkinter.CTkFrame(main_container, height=self.ui.size(50))
        header.pack(fill="x", pady=(0, self.ui.size(12)))
        header.pack_propagate(False)  # Prevent header from shrinking
        
        # Application title
        title_label = customtkinter.CTkLabel(
            header, 
            text="Monitor Input Switcher", 
            font=self.ui.font("Arial", 20, "bold")
        )
        title_label.pack(side="left", padx=self.ui.size(10), pady=self.ui.size(10))
        
        # Easter egg: Click title 5 times to reveal hidden dialog
        title_label.bind("<Button-1>", self._on_title_click)

        # Header button frame (right side) - contains theme, shortcuts, settings buttons
        btn_frame = customtkinter.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right", padx=self.ui.size(10))
        
        # Theme button (🎨) - opens theme settings dialog
        self.theme_button = customtkinter.CTkButton(
            btn_frame, 
            text="🎨", 
            command=self.show_theme_settings,
            width=self.ui.size(35),
            height=self.ui.size(35),
            font=self.ui.font("Arial", 16)
        )
        self.theme_button.pack(side="right", padx=2)
        
        # Keyboard shortcuts button (⌨) - opens shortcuts editor
        # Disabled until monitors are detected
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

        # Settings button (⚙) - opens general settings dialog (tray behavior, etc.)
        self.settings_button = customtkinter.CTkButton(
            btn_frame,
            text="⚙",
            command=self.show_settings,
            width=self.ui.size(35),
            height=self.ui.size(35),
            font=self.ui.font("Arial", 16)
            )
        self.settings_button.pack(side="right", padx=2)

        # Track open dialogs and loading state so they can be disabled during refresh
        # These references allow us to disable dialogs when monitor refresh is in progress
        self.settings_window = None    # Settings dialog window
        self.theme_window = None       # Theme settings dialog window
        self.manage_window = None      # Manage favorites dialog window
        self.editor_window = None      # Shortcuts editor dialog window
        self._loading_monitors = False # Flag indicating monitor detection in progress

        # ==================================================================
        # MAIN UI LAYOUT - MONITOR SELECTION CARD
        # ==================================================================
        
        monitor_card = customtkinter.CTkFrame(main_container)
        monitor_card.pack(fill="x", pady=(0, self.ui.size(10)))
        
        # Monitor card header with refresh button
        monitor_header = customtkinter.CTkFrame(monitor_card, fg_color="transparent")
        monitor_header.pack(fill="x", padx=self.ui.size(12), pady=(self.ui.size(12), self.ui.size(8)))
        
        self.monitor_label = customtkinter.CTkLabel(
            monitor_header, 
            text="📺 Select Monitor", 
            font=self.ui.font("Arial", 13, "bold")
        )
        self.monitor_label.pack(side="left")
        
        # Refresh button - triggers re-detection of connected monitors
        self.refresh_button = customtkinter.CTkButton(
            monitor_header, 
            text="Refresh🔄",
            command=self.refresh_monitors,
            width=self.ui.size(30),
            height=self.ui.size(28),
            font=self.ui.font("Arial", 14)
        )
        self.refresh_button.pack(side="right")

        # Monitor dropdown menu - populated after detection
        self.monitor_menu = customtkinter.CTkOptionMenu(
            monitor_card, 
            values=["Loading..."],
            command=self.update_inputs,  # Callback when selection changes
            height=self.ui.size(32),
            font=self.ui.font("Arial", 12)
        )
        self.monitor_menu.set("Loading...")
        self.monitor_menu.pack(fill="x", padx=self.ui.size(12), pady=(0, self.ui.size(12)))

        # ==================================================================
        # MAIN UI LAYOUT - INPUT SOURCE CARD
        # ==================================================================
        
        input_card = customtkinter.CTkFrame(main_container)
        input_card.pack(fill="x", pady=(0, self.ui.size(10)))
        
        self.input_label = customtkinter.CTkLabel(
            input_card, 
            text="🔌 Select Input Source", 
            font=self.ui.font("Arial", 13, "bold")
        )
        self.input_label.pack(anchor="w", padx=self.ui.size(12), pady=(self.ui.size(12), self.ui.size(8)))

        # Input source dropdown - populated based on selected monitor's capabilities
        self.input_menu = customtkinter.CTkOptionMenu(
            input_card, 
            values=["Loading..."],
            height=self.ui.size(32),
            font=self.ui.font("Arial", 12)
        )
        self.input_menu.set("Loading...")
        self.input_menu.pack(fill="x", padx=self.ui.size(12), pady=(0, self.ui.size(12)))

        # ==================================================================
        # MAIN UI LAYOUT - SWITCH BUTTON
        # ==================================================================
        
        # Main action button - switches the selected monitor to the selected input
        self.switch_button = customtkinter.CTkButton(
            main_container,
            text="⚡ Switch Input",
            command=self.switch_input,
            height=self.ui.size(42),
            font=self.ui.font("Arial", 14, "bold"),
            fg_color=("#2B7A0B", "#5FB041"),      # Green colors (light/dark mode)
            hover_color=("#246A09", "#52A038")
        )
        self.switch_button.pack(fill="x", pady=(0, self.ui.size(10)))

        # Progress bar (hidden by default) - shown during monitor detection
        self.progress_bar = customtkinter.CTkProgressBar(main_container, mode='indeterminate')

        # ==================================================================
        # MAIN UI LAYOUT - FAVORITES SECTION
        # ==================================================================
        
        favorites_card = customtkinter.CTkFrame(main_container)
        # Don't expand by default; will grow dynamically when favorites are added
        favorites_card.pack(fill="x", expand=False, pady=(0, self.ui.size(10)))
        
        # Favorites header with manage button
        fav_header = customtkinter.CTkFrame(favorites_card, fg_color="transparent")
        fav_header.pack(fill="x", padx=self.ui.size(12), pady=(self.ui.size(12), self.ui.size(8)))
        
        self.favorites_label = customtkinter.CTkLabel(
            fav_header, 
            text="⭐ Quick Favorites", 
            font=self.ui.font("Arial", 13, "bold")
        )
        self.favorites_label.pack(side="left")

        # Manage favorites button - opens favorites management dialog
        # Disabled until monitors are detected
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

        # Favorites container - holds favorite buttons in a grid layout
        # Regular frame without scrolling, minimal height when empty
        self.favorites_scroll = customtkinter.CTkFrame(
            favorites_card,
            fg_color="transparent",
            height=self.ui.size(40)
        )
        self.favorites_scroll.pack(fill="x", expand=False, padx=self.ui.size(12), pady=(0, self.ui.size(12)))
        self.favorites_scroll.pack_propagate(False)

        # ==================================================================
        # MAIN UI LAYOUT - STATUS BAR
        # ==================================================================
        
        status_frame = customtkinter.CTkFrame(main_container, height=self.ui.size(40))
        status_frame.pack(fill="x", pady=(0, 0))
        status_frame.pack_propagate(False)
        
        # Status label - displays operation results and feedback messages
        self.status_label = customtkinter.CTkLabel(
            status_frame,
            text="Ready",
            font=self.ui.font("Arial", 11),
            wraplength=self.ui.size(480)  # Wrap long messages
        )
        self.status_label.pack(pady=self.ui.size(8))

        # ==================================================================
        # MAIN UI LAYOUT - FOOTER
        # ==================================================================
        
        # Footer with author credit
        footer = customtkinter.CTkLabel(
            main_container,
            text="By: LuqmanHakimAmiruddin@PDC",
            font=self.ui.font("Arial", 9),
            text_color="gray"
        )
        footer.pack(pady=(self.ui.size(5), 0))

        # ==================================================================
        # START INITIAL MONITOR DETECTION
        # ==================================================================
        
        # Trigger monitor detection after a brief delay to allow UI to render
        self.after(100, self.refresh_monitors)

    def refresh_monitors(self):
        """
        Initiate asynchronous monitor detection and refresh the UI.
        
        This method starts a background thread to detect connected monitors
        using DDC/CI protocol. While detection is in progress:
        - UI controls are disabled to prevent user interaction
        - Progress bar is shown to indicate activity
        - Any open dialogs are disabled
        
        The actual detection happens in load_monitor_data_thread() and
        UI is updated in update_ui_after_load() when detection completes.
        
        Thread Safety:
            Uses threading.Thread with daemon=True so the thread is
            automatically terminated when the main application exits.
        """
        # Update status and show progress indicator
        self.status_label.configure(text="🔍 Detecting monitors...")
        self.progress_bar.pack(pady=(0, 10), fill="x")
        self.progress_bar.start()

        # Disable all interactive controls while loading
        self.switch_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        
        # Gray-out monitor/input dropdowns and set placeholder text
        self.monitor_menu.configure(values=["Loading..."], state="disabled")
        self.monitor_menu.set("Loading...")
        self.input_menu.configure(values=["Loading..."], state="disabled")
        self.input_menu.set("Loading...")
        
        # Disable header buttons until monitors are detected
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

        # Mark loading state and disable any open dialogs during refresh
        # This prevents users from interacting with stale data
        self._loading_monitors = True
        try:
            self._set_toplevels_state('disabled')
        except Exception:
            pass

        # Start background thread for monitor detection
        # daemon=True ensures thread terminates with main app
        thread = threading.Thread(target=self.load_monitor_data_thread, daemon=True)
        thread.start()

    def load_monitor_data_thread(self):
        """
        Background thread function for monitor detection.
        
        This method runs in a separate thread to prevent the GUI from
        freezing during monitor detection (which can take several seconds).
        
        On Windows, COM must be initialized for each thread that uses WMI,
        hence the pythoncom.CoInitialize/CoUninitialize calls.
        
        After detection completes, schedules update_ui_after_load() to
        run on the main thread using self.after(0, ...).
        """
        # Initialize COM for WMI access on Windows (required per-thread)
        if platform.system() == 'Windows':
            pythoncom.CoInitialize()
        try:
            # Perform the actual monitor detection
            self.monitors_data = self.get_all_monitor_data()
        finally:
            # Clean up COM on Windows
            if platform.system() == 'Windows':
                pythoncom.CoUninitialize()
        
        # Schedule UI update on main thread (thread-safe)
        self.after(0, self.update_ui_after_load)

    def update_ui_after_load(self):
        """
        Update the UI after monitor detection completes.
        
        This method is called on the main thread after the background
        detection thread finishes. It:
        1. Populates the monitor dropdown with detected monitors
        2. Updates the input dropdown for the first monitor
        3. Re-enables all UI controls
        4. Refreshes the favorites buttons
        5. Hides the progress bar
        
        If no monitors are detected, appropriate error messages are shown
        and shortcuts/favorites remain disabled.
        """
        # Extract display names from monitor data for dropdown
        self.monitor_names = [data['display_name'] for data in self.monitors_data]
        
        # Update monitor dropdown with detected monitors
        self.monitor_menu.configure(values=self.monitor_names)
        
        if self.monitor_names:
            # Monitors found - set up UI for normal operation
            self.monitor_menu.set(self.monitor_names[0])
            
            # Re-enable monitor and input controls
            try:
                self.monitor_menu.configure(state="normal")
            except Exception:
                pass
            try:
                self.input_menu.configure(state="normal")
            except Exception:
                pass
            
            # Update input dropdown for the first monitor
            self.update_inputs(self.monitor_names[0])
            
            # Update status and enable buttons
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
            
            # Refresh favorite buttons with current monitor data
            self.refresh_favorites_buttons()
        else:
            # No monitors detected - show error state
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
            
            # Keep shortcuts and favorites disabled when no monitors available
            self.shortcuts_button.configure(state="disabled")
            self.manage_favorites_btn.configure(state="disabled")
            
            # Keep settings and theme available so user can change preferences
            try:
                self.settings_button.configure(state="normal")
            except Exception:
                pass
            try:
                self.theme_button.configure(state="normal")
            except Exception:
                pass

        # Hide progress bar and re-enable action buttons
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
        """
        Detect all connected monitors and gather their information.
        
        This method performs DDC/CI communication to detect monitors and
        retrieve their capabilities including:
        - Brand name (from PnP ID or model prefix)
        - Model name (from VCP capabilities or EDID)
        - Available input sources
        - Current input source
        
        Returns:
            list: List of dictionaries containing monitor data:
                - 'display_name': Human-readable name (e.g., "Samsung - C27G2")
                - 'inputs': List of available input names (e.g., ["HDMI1", "DP1"])
                - 'id': Monitor index for addressing
                - 'current_input': Currently selected input name
        
        Technical Details:
            - Uses monitorcontrol library for DDC/CI communication
            - Uses WMI on Windows to get PnP Device IDs for brand detection
            - Reads EDID data from registry for model detection fallback
            - Skips internal laptop displays (identified by specific PnP codes)
        """
        all_data = []
        pnp_ids = []

        # FIX #2: Refresh monitors list each time this method is called
        # This ensures newly connected/disconnected monitors are detected
        self.monitors = get_monitors()

        try:
            logging.info(f"Found {len(self.monitors)} monitors.")
            
            # Log display adapter information for debugging
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

        # ------------------------------------------------------------------
        # COLLECT PNP DEVICE IDS FROM WMI (Windows only)
        # ------------------------------------------------------------------
        # FIX #1: Collect PnP IDs from WMI once (moved outside the monitor loop)
        # Previously this was nested inside 'for monitor in monitors:' and used
        # 'for monitor in wmi_monitors:' which shadowed the outer variable,
        # causing only 1 monitor to be processed.
        if platform.system() == "Windows":
            try:
                c = wmi.WMI()
                wmi_monitors = c.Win32_DesktopMonitor()
                for wmi_mon in wmi_monitors:
                    pnp_ids.append(getattr(wmi_mon, 'PNPDeviceID', None))
            except Exception as e:
                logging.error(f"Failed to get device information from WMI: {e}")
        logging.info(f"WMI PnP IDs: {pnp_ids}")

        # ------------------------------------------------------------------
        # HELPER FUNCTIONS FOR EDID PARSING
        # ------------------------------------------------------------------
        
        def read_edid(pnp_id):
            """
            Read EDID (Extended Display Identification Data) from Windows registry.
            
            EDID is a standardized data structure that contains information about
            the monitor including manufacturer, model, and supported resolutions.
            
            Args:
                pnp_id: The PnP Device ID string from WMI
                
            Returns:
                bytes: Raw EDID data or None if not found
            """
            try:
                import winreg
                # EDID is stored in the monitor's Device Parameters registry key
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\\CurrentControlSet\\Enum\\" + pnp_id + r"\Device Parameters"
                )
                edid_data, _ = winreg.QueryValueEx(key, "EDID")
                return edid_data
            except Exception:
                return None

        def parse_edid(edid):
            """
            Extract model name from EDID data.
            
            The model name is stored as ASCII text in bytes 54-72 of the EDID
            (specifically in the descriptor blocks which start at byte 54).
            
            Args:
                edid: Raw EDID bytes
                
            Returns:
                str: Model name or "Unknown" if parsing fails
            """
            try:
                # Extract printable ASCII characters from descriptor block
                model = "".join(chr(c) for c in edid[54:72] if 32 <= c <= 126).strip()
                return model if model else "Unknown"
            except Exception:
                return "Unknown"

        # ------------------------------------------------------------------
        # PROCESS EACH DETECTED MONITOR
        # ------------------------------------------------------------------
        
        for i, monitor_obj in enumerate(self.monitors):
            # Skip internal laptop displays on Windows
            # These are identified by specific PnP codes like SHP, BOE, LGD, etc.
            if platform.system() == "Windows" and i < len(pnp_ids) and pnp_ids[i]:
                pnp_id_str = pnp_ids[i].upper()
                # Common internal display manufacturer codes
                if any(x in pnp_id_str for x in ["SHP", "BOE", "LGD", "AUO", "SEC", "EDP"]):
                    logging.info(f"Skipping internal laptop display at index {i} ({pnp_id_str})")
                    continue

            model = "Unknown"
            brand = "Unknown"

            # ------------------------------------------------------------------
            # GET MODEL NAME FROM VCP CAPABILITIES
            # ------------------------------------------------------------------
            try:
                with monitor_obj:
                    caps = monitor_obj.get_vcp_capabilities()
                    model = caps.get('model', "Unknown")
            except:
                pass

            # Fallback: Try to get model from EDID if VCP didn't provide it
            if model == "Unknown" and platform.system() == "Windows" and i < len(pnp_ids) and pnp_ids[i]:
                edid = read_edid(pnp_ids[i])
                if edid:
                    model = parse_edid(edid)

            # ------------------------------------------------------------------
            # DETERMINE BRAND NAME
            # ------------------------------------------------------------------
            if platform.system() == "Windows":
                # First try: Get brand from PNP manufacturer code (first 3 chars)
                if brand == "Unknown" and i < len(pnp_ids):
                    try:
                        if pnp_ids[i]:
                            # PnP ID format: MANUFACTURER\MODEL\SERIAL
                            # Extract the 3-letter manufacturer code
                            pnp_code = pnp_ids[i].split('\\')[1][:3].upper()
                            brand = PNP_IDS.get(pnp_code, "Unknown")
                    except Exception:
                        pass
               
                # Fallback: Match model prefix to known brand patterns
                if brand == "Unknown" and model != "Unknown":
                    model_upper = model.upper()
                    for prefix, brand_name in MODEL_BRAND_MAP.items():
                        if model_upper.startswith(prefix):
                            brand = brand_name
                            break

            # ------------------------------------------------------------------
            # GET AVAILABLE INPUT SOURCES
            # ------------------------------------------------------------------
            try:
                input_names = []
                with monitor_obj:
                    caps = monitor_obj.get_vcp_capabilities()
                    inputs = caps.get('inputs', [])
                    
                    for inp in inputs:
                        if hasattr(inp, 'name'):
                            # Standard InputSource enum member
                            input_names.append(inp.name)
                        elif isinstance(inp, int):
                            # Raw integer code - map to known types or display as-is
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

            # ------------------------------------------------------------------
            # GET CURRENT INPUT SOURCE
            # ------------------------------------------------------------------
            try:
                with monitor_obj:
                    current_input = monitor_obj.get_input_source()
                    if hasattr(current_input, 'value'):
                        # Standard InputSource enum member
                        current_code = current_input.value
                        current_name = current_input.name if hasattr(current_input, 'name') else str(current_input)
                    else:
                        # Raw integer code
                        current_code = int(current_input)
                        current_name = get_input_name(current_code)
            except Exception as e:
                    logging.warning(f"⚠️  Could not read current input: {e}")
                    current_code = None
                    current_name = "Unknown"

            # ------------------------------------------------------------------
            # ADD MONITOR DATA TO RESULTS
            # ------------------------------------------------------------------
            all_data.append({
                "display_name": f"{brand} - {model}",  # e.g., "Samsung - C27G2"
                "inputs": input_names,                  # e.g., ["HDMI1", "DP1", "USB-C"]
                "id": i,                               # Monitor index for addressing
                "current_input": current_name          # e.g., "HDMI1"
            })

        logging.info(f"All monitor data: {all_data}")
        return all_data

    def update_inputs(self, selected_monitor_name):
        """
        Update the input source dropdown based on the selected monitor.
        
        This method is called when the user selects a different monitor
        from the dropdown. It populates the input dropdown with the
        available inputs for that specific monitor and pre-selects the
        current input if possible.
        
        Args:
            selected_monitor_name: The display name of the selected monitor
                                   (e.g., "Samsung - C27G2")
        """
        # Find the monitor data matching the selected name
        for data in self.monitors_data:
            if data['display_name'] == selected_monitor_name:
                self.selected_monitor_data = data
                break
        
        # Update input dropdown with available inputs for selected monitor
        self.input_menu.configure(values=self.selected_monitor_data['inputs'])
        
        if self.selected_monitor_data['inputs']:
            # Try to pre-select the current input if it's in the available list
            current_input = self.selected_monitor_data.get('current_input', "Unknown")
            if current_input in self.selected_monitor_data['inputs']:
                self.input_menu.set(current_input)
            else:
                # Fall back to first available input
                self.input_menu.set(self.selected_monitor_data['inputs'][0])
        else:
            self.input_menu.set("No inputs found")

    def _position_on_active_display(self):
        """
        Position the window on a display that is actively showing PC content.
        
        When a monitor is switched to a different input (e.g., showing a game
        console instead of PC), DDC/CI commands may fail on that monitor.
        This method finds monitors that respond to DDC/CI queries and
        positions the app window on one of them.
        
        Use Case:
            User has dual monitors. Monitor 1 is showing the PC, Monitor 2 is
            showing a PlayStation. This method ensures the app window appears
            on Monitor 1 (the active PC display).
        """
        try:
            all_screens = get_screen_info()
            if not all_screens or len(all_screens) <= 1:
                return  # Only one screen or none, use default positioning
            
            # Get DDC/CI monitors to check which are showing PC content
            ddc_monitors = get_monitors()
            if not ddc_monitors:
                return
            
            # Find monitors that respond to DDC/CI (indicating they're showing PC input)
            # Monitors showing other inputs (console, etc.) won't respond to get_input_source()
            active_indices = []
            for i, mon in enumerate(ddc_monitors):
                try:
                    with mon:
                        mon.get_input_source()  # Will fail if not showing PC
                        active_indices.append(i)
                except Exception:
                    pass  # Monitor not showing PC input
            
            if not active_indices:
                return
            
            # Get current window position to find which screen it's on
            self.update_idletasks()
            app_x, app_y = self.winfo_x(), self.winfo_y()
            
            # Find current screen based on window position
            current_screen = None
            current_screen_idx = 0
            for idx, screen in enumerate(all_screens):
                if (screen.x <= app_x < screen.x + screen.width and
                    screen.y <= app_y < screen.y + screen.height):
                    current_screen = screen
                    current_screen_idx = idx
                    break
            
            # If current screen is not showing PC content, move to an active screen
            if current_screen_idx not in active_indices:
                # Find an active screen to move to
                for idx in active_indices:
                    if idx < len(all_screens):
                        new_screen = all_screens[idx]
                        # Position window 50 pixels from top-left corner
                        self.geometry(f"+{new_screen.x + 50}+{new_screen.y + 50}")
                        self.update_idletasks()
                        logging.info(f"Positioned app on active display {idx}")
                        break
        except Exception as e:
            logging.debug(f"Could not position on active display: {e}")
    
    def move_app_if_on_switching_monitor(self, monitor_id):
        """
        Move the app window to another monitor if it's on the monitor being switched.
        
        When switching a monitor's input away from PC, the window would become
        invisible to the user. This method detects if the app is on the target
        monitor and moves it to a different screen before the switch.
        
        Args:
            monitor_id: The index of the monitor being switched
            
        Example:
            User clicks "Switch to HDMI1 (PlayStation)" on Monitor 1 while the
            app window is on Monitor 1. This method moves the app to Monitor 2
            so the user can still see and interact with the app.
        """
        try:
            all_screens = get_screen_info()
            screen_to_switch = all_screens[monitor_id] if monitor_id < len(all_screens) else None
            
            if not screen_to_switch:
                return
            
            # Get app's current screen position
            app_x = self.winfo_x()
            app_y = self.winfo_y()
            app_current_screen = None
            
            # Find which screen the app is currently on
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
                    self.update_idletasks()  # Ensure the move is processed before switching
        except Exception as e:
            logging.warning(f"Failed to move app window: {e}")

    def switch_input(self):
        """
        Switch the selected monitor to the selected input source.
        
        This is the main action handler for the "Switch Input" button.
        It reads the selected monitor and input from the dropdowns and
        sends the DDC/CI command to change the monitor's input.
        
        The method also:
        - Moves the app window if it's on the monitor being switched
        - Handles special input codes (USB-C, Thunderbolt, custom codes)
        - Updates the status label with success/failure messages
        """
        new_input_str = self.input_menu.get()
        logging.info(f"Input name: {new_input_str}")
        
        # Validate that we have a valid selection
        if new_input_str == "No inputs found" or not hasattr(self, 'selected_monitor_data'):
            self.status_label.configure(text="❌ Cannot switch: No monitor or input selected")
            return

        try:
            selected_monitor_id = self.selected_monitor_data['id']
            logging.info(f"Current Monitor ID: {selected_monitor_id}")

            # Move app to a different monitor if it's on the one being switched
            # This prevents the window from becoming invisible
            self.move_app_if_on_switching_monitor(selected_monitor_id)

            # Convert input name string to the appropriate DDC/CI code
            if new_input_str == "USB-C":
                new_input = VCP_INPUT_USB_C  # Code 27
            elif new_input_str == "THUNDERBOLT":
                new_input = VCP_INPUT_THUNDERBOLT  # Code 26
            elif new_input_str.startswith("INPUT_"):
                # Handle unknown input codes (INPUT_XX format)
                new_input = int(new_input_str.split('_')[1])
            else:
                # Standard InputSource enum values (HDMI1, DP1, etc.)
                new_input = getattr(InputSource, new_input_str)
            logging.info(f"Input name: {new_input}")

            # Send the DDC/CI command to switch input
            with self.monitors[selected_monitor_id] as monitor:
                logging.info(f"monitor: {monitor}")
                monitor.set_input_source(new_input)
            logging.info(f"Input name after: {new_input}")

            # Show success message with monitor name
            monitor_name = self.selected_monitor_data.get('display_name', f'Monitor {selected_monitor_id}')
            self.status_label.configure(text=f"✅ {monitor_name}: Switched to {new_input_str}")
            logging.info(f"Successfully switched {monitor_name} to {new_input_str}")

        except Exception as e:
            # Show error message (truncated to fit in status bar)
            self.status_label.configure(text=f"❌ Error: {str(e)[:50]}")
            logging.error(f"Failed to switch input: {e}")

    def setup_global_hotkeys(self):
        """
        Register global keyboard shortcuts for quick input switching.
        
        Global hotkeys work even when the application is minimized or not
        focused. This allows users to quickly switch monitor inputs using
        keyboard shortcuts from any application.
        
        Registered Hotkeys:
            - User-defined shortcuts from self.shortcuts dictionary
            - Ctrl+Shift+H: Always registered to show shortcuts help dialog
        
        Note:
            Uses the 'keyboard' library which requires appropriate permissions
            on some systems (e.g., accessibility permissions on macOS).
        """
        try:
            # Register each user-defined shortcut
            for shortcut, (monitor_id, input_source) in self.shortcuts.items():
                keyboard.add_hotkey(
                    shortcut,
                    # Lambda captures m and i by value to avoid closure issues
                    lambda m=monitor_id, i=input_source: self.handle_global_hotkey(m, i)
                )
            
            # Always register the help hotkey (Ctrl+Shift+H)
            keyboard.add_hotkey('ctrl+shift+h', self.show_shortcuts_help)
            logging.info("Global hotkeys registered successfully")
        except Exception as e:
            logging.error(f"Failed to register global hotkeys: {e}")

    def handle_global_hotkey(self, monitor_id, input_source):
        """
        Handle a global hotkey press by switching the specified monitor to the specified input.
        
        This method is called when a registered global hotkey is pressed.
        It performs the same input switching as switch_input() but with
        pre-specified monitor and input values.
        
        Args:
            monitor_id: Index of the monitor to switch
            input_source: Name of the input source (e.g., "HDMI1", "USB-C")
        """
        try:
            # Validate monitor exists
            if monitor_id < len(self.monitors):
                # Get monitor display name for status message
                monitor_name = f"Monitor {monitor_id}"
                for data in self.monitors_data:
                    if data.get('id') == monitor_id:
                        monitor_name = data.get('display_name', monitor_name)
                        break
                
                # Move app window if it's on the monitor being switched
                self.move_app_if_on_switching_monitor(monitor_id)
                
                with self.monitors[monitor_id] as monitor:
                    # Convert input source name to DDC/CI code
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
                    
                    # Send DDC/CI command
                    monitor.set_input_source(input_obj)
                    self.status_label.configure(text=f"✅ {monitor_name}: Switched to {input_source}")
                    logging.info(f"Hotkey: Switched {monitor_name} to {input_source}")
        except Exception as e:
            self.status_label.configure(text=f"❌ Hotkey error: {str(e)[:40]}")
            logging.error(f"Hotkey error: {e}")

    # ==========================================================================
    # PERSISTENT DATA MANAGEMENT
    # ==========================================================================

    def load_shortcuts(self):
        """
        Load keyboard shortcuts from JSON file.
        
        Returns:
            dict: Dictionary mapping shortcut keys to (monitor_id, input_source) tuples,
                  or None if loading fails or file doesn't exist.
        """
        try:
            if os.path.exists(self.shortcuts_file):
                with open(self.shortcuts_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Error loading shortcuts: {e}")
        return None

    def save_shortcuts(self):
        """
        Save keyboard shortcuts to JSON file.
        
        Saves the current self.shortcuts dictionary to the shortcuts file
        with pretty-printing for readability.
        """
        try:
            with open(self.shortcuts_file, 'w') as f:
                json.dump(self.shortcuts, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving shortcuts: {e}")

    def load_favorites(self):
        """
        Load favorites from JSON file.
        
        Returns:
            dict: Dictionary mapping favorite names to (monitor_id, input_source) tuples,
                  or None if loading fails or file doesn't exist.
        """
        try:
            if os.path.exists(self.favorites_file):
                with open(self.favorites_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Error loading favorites: {e}")
        return None

    def save_favorites(self):
        """
        Save favorites to JSON file.
        
        Saves the current self.favorites dictionary to the favorites file
        with pretty-printing for readability.
        """
        try:
            with open(self.favorites_file, 'w') as f:
                json.dump(self.favorites, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving favorites: {e}")

    def load_settings(self):
        """
        Load application settings from JSON file.
        
        Returns:
            dict: Settings dictionary with keys like 'theme' and 'tray_on',
                  or None if loading fails or file doesn't exist.
        """
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Error loading settings: {e}")
        return None

    def save_settings(self):
        """
        Save application settings to JSON file.
        
        Saves the current self.settings dictionary to the settings file
        with pretty-printing for readability.
        """
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving settings: {e}")

    def apply_theme(self):
        """
        Apply the current theme setting to the application.
        
        Reads the 'theme' value from settings and applies it using
        CustomTkinter's set_appearance_mode() function.
        
        Valid themes: "dark", "light", "system"
        - "system" automatically follows Windows light/dark mode setting
        """
        try:
            theme = self.settings.get("theme", "system")
            if theme in AVAILABLE_THEMES:
                customtkinter.set_appearance_mode(theme)
        except Exception as e:
            logging.error(f"Error applying theme: {e}")

    # ==========================================================================
    # DIALOG STATE MANAGEMENT
    # ==========================================================================

    def _recursive_set_state(self, widget, state):
        """
        Recursively set the enabled/disabled state for a widget and all children.
        
        This is used to disable entire dialog windows during monitor refresh
        to prevent users from interacting with stale data.
        
        Args:
            widget: The parent widget to start from
            state: "normal" or "disabled"
        """
        try:
            widget.configure(state=state)
        except Exception:
            pass  # Not all widgets support state configuration
        for child in widget.winfo_children():
            self._recursive_set_state(child, state)

    def _set_toplevels_state(self, state):
        """
        Set the enabled/disabled state for all open Toplevel dialogs.
        
        Iterates through tracked dialog windows (settings, theme, manage,
        editor) and disables/enables them. Used during monitor refresh
        to prevent interaction with stale data.
        
        Args:
            state: "normal" or "disabled"
        """
        for attr in ('settings_window', 'theme_window', 'manage_window', 'editor_window'):
            win = getattr(self, attr, None)
            if win:
                try:
                    self._recursive_set_state(win, state)
                except Exception:
                    logging.debug(f"Failed to set state {state} for {attr}")

    # ==========================================================================
    # FAVORITES MANAGEMENT
    # ==========================================================================

    def add_favorite(self, name, monitor_id, input_source):
        """
        Add a new favorite configuration.
        
        Args:
            name: Display name for the favorite (max 20 characters)
            monitor_id: Index of the monitor
            input_source: Name of the input source (e.g., "HDMI1")
            
        Returns:
            bool: True if successfully added, False otherwise
        """
        try:
            # Validate inputs
            if not name or not isinstance(name, str):
                return False
            monitor_id = int(monitor_id)
            if not isinstance(input_source, str):
                return False
            
            # Add to favorites dictionary and save
            self.favorites[name] = (monitor_id, input_source)
            self.save_favorites()
            logging.info(f"Added favorite '{name}': Monitor {monitor_id} → {input_source}")
            return True
        except Exception as e:
            logging.error(f"Failed to add favorite: {e}")
            return False

    def remove_favorite(self, name):
        """
        Remove a favorite configuration by name.
        
        Args:
            name: Name of the favorite to remove
            
        Returns:
            bool: True if successfully removed, False otherwise
        """
        try:
            if name in self.favorites:
                del self.favorites[name]
                self.save_favorites()
                logging.info(f"Removed favorite '{name}'")
                return True
        except Exception as e:
            logging.error(f"Failed to remove favorite: {e}")
        return False

    # ==========================================================================
    # HELPER METHODS FOR FAVORITE/SHORTCUT DIALOGS
    # ==========================================================================
    # FIX #6 & #7: These helper methods reduce duplicate code across dialogs
    
    def _validate_favorite_name(self, name, exclude_name=None):
        """
        Validate a favorite name according to naming rules.
        
        Checks:
        - Name is not empty
        - Name is within length limit (20 characters)
        - Name doesn't contain invalid characters
        - Name is not a duplicate (case-insensitive)
        
        Args:
            name: The name to validate
            exclude_name: Optional name to exclude from duplicate check
                          (used when editing an existing favorite)
        
        Returns:
            tuple: (is_valid: bool, error_message: str or None)
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
        
        # Check for duplicates (case-insensitive comparison)
        for existing_name in self.favorites.keys():
            if existing_name.lower() == name.lower():
                # Allow if we're editing this exact favorite
                if exclude_name is None or existing_name.lower() != exclude_name.lower():
                    return False, f"A favorite named '{existing_name}' already exists"
        
        return True, None

    def _get_inputs_for_monitor(self, monitor_id):
        """
        Get the list of available input sources for a specific monitor.
        
        Args:
            monitor_id: Index of the monitor
            
        Returns:
            list: List of input source names (e.g., ["HDMI1", "DP1"]) or empty list
        """
        monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else []
        for mon in monitors_list:
            if mon.get('id') == monitor_id:
                return mon.get('inputs', []) or []
        return []

    def _get_monitor_choices(self):
        """
        Get list of monitor choices formatted for dropdown menus.
        
        Returns:
            list: List of strings in format "ID: Display Name" 
                  (e.g., ["0: Samsung - C27G2", "1: Dell - P2419H"])
        """
        monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else []
        if monitors_list:
            return [f"{m.get('id')}: {m.get('display_name')}" for m in monitors_list]
        return ["0"]

    def _parse_monitor_selection(self, selection):
        """
        Parse monitor ID from a dropdown selection string.
        
        Args:
            selection: String in format "ID: Display Name" (e.g., "0: Samsung - C27G2")
            
        Returns:
            int: The monitor ID, or 0 if parsing fails
        """
        try:
            return int(selection.split(':', 1)[0].strip()) if ':' in selection else int(selection)
        except (ValueError, AttributeError):
            return 0

    def _center_dialog_on_parent(self, dialog, parent, width=None, height=None):
        """
        Center a dialog window on its parent window.
        
        Works correctly across multiple monitors with different positions,
        including negative coordinates for monitors to the left of primary.
        
        Args:
            dialog: The dialog window (Toplevel) to center
            parent: The parent window to center on
            width: Optional base width (will be scaled using UI scaler)
            height: Optional base height (will be scaled using UI scaler)
        """
        # Ensure both parent and dialog geometries are fully calculated
        parent.update_idletasks()
        dialog.update_idletasks()
        
        # Scale the provided dimensions, or use dialog's requested size
        dlg_width = self.ui.size(width) if width else dialog.winfo_reqwidth()
        dlg_height = self.ui.size(height) if height else dialog.winfo_reqheight()
        
        # Get parent's absolute position on the virtual screen
        # winfo_x/winfo_y give the window's top-left position
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
        # The dialog just needs to be at least partially visible
        dialog.geometry(f"{dlg_width}x{dlg_height}+{x}+{y}")

    def switch_to_favorite(self, name):
        """
        Switch to a saved favorite configuration.
        
        Looks up the favorite by name and switches the specified monitor
        to the specified input source.
        
        Args:
            name: Name of the favorite to switch to
            
        Returns:
            bool: True if successfully switched, False otherwise
        """
        try:
            # Validate favorite exists
            if name not in self.favorites:
                self.status_label.configure(text=f"❌ Favorite '{name}' not found")
                return False

            monitor_id, input_source = self.favorites[name]

            # Validate monitor exists
            if monitor_id >= len(self.monitors):
                self.status_label.configure(text=f"❌ Monitor {monitor_id} not found")
                return False

            # Get monitor display name for status message
            monitor_name = f"Monitor {monitor_id}"
            for data in self.monitors_data:
                if data.get('id') == monitor_id:
                    monitor_name = data.get('display_name', monitor_name)
                    break

            # Move app if it's on the monitor being switched
            self.move_app_if_on_switching_monitor(monitor_id)

            # Convert input_source string to DDC/CI code
            input_obj = None
            # Normalize the input source string (handle USB-C, THUNDERBOLT, etc.)
            normalized = input_source.replace("-", "_").replace(" ", "_").upper()
            
            if hasattr(InputSource, normalized):
                # Standard InputSource enum attribute
                input_obj = getattr(InputSource, normalized)
            elif input_source.upper() == "USB-C":
                # Fallback to known code for USB-C
                input_obj = VCP_INPUT_USB_C  # 27
            elif input_source.upper() == "THUNDERBOLT":
                input_obj = VCP_INPUT_THUNDERBOLT  # 26
            else:
                # Try to parse as int code (e.g., INPUT_27)
                try:
                    if input_source.startswith("INPUT_"):
                        input_obj = int(input_source.split("_")[-1])
                except Exception:
                    pass

            # Send DDC/CI command
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
        """
        Add a new global keyboard shortcut.
        
        Registers a keyboard shortcut that will switch the specified monitor
        to the specified input source when pressed from any application.
        
        Args:
            shortcut_key: Keyboard shortcut string (e.g., "ctrl+alt+1")
            monitor_id: Index of the monitor to switch
            input_source: Name of the input source (e.g., "HDMI1")
            
        Returns:
            bool: True if successfully added, False otherwise
        """
        try:
            # Validate inputs
            if not isinstance(shortcut_key, str) or not shortcut_key:
                return False
            monitor_id = int(monitor_id)
            if not isinstance(input_source, str) or not input_source:
                return False

            # Add to shortcuts dictionary and save
            self.shortcuts[shortcut_key] = (monitor_id, input_source)
            self.save_shortcuts()
            
            # Re-register all hotkeys (clear and recreate)
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
        """
        Rebuild the favorites buttons grid in the main window.
        
        This method clears and recreates all favorite buttons based on
        the current favorites dictionary. Buttons are arranged in a
        responsive grid layout with up to 4 columns.
        
        The favorites section height is dynamically adjusted based on
        the number of favorites (minimal height when empty).
        """
        # Clear existing buttons
        for widget in self.favorites_scroll.winfo_children():
            widget.destroy()
        
        if not self.favorites:
            # When empty, show placeholder text and keep minimal height
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
        max_cols = 4  # Maximum columns per row
        row = 0
        col = 0

        for fav_name in self.favorites.keys():
            # Create button for each favorite
            fav_btn = customtkinter.CTkButton(
                self.favorites_scroll,
                text=fav_name,
                command=lambda n=fav_name: self.switch_to_favorite(n),
                height=self.ui.size(36),
                font=self.ui.font("Arial", 11)
            )
            fav_btn.grid(row=row, column=col, padx=self.ui.size(6), pady=self.ui.size(6), sticky="ew")

            # Move to next column, wrap to next row if needed
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

    # ==========================================================================
    # SETTINGS DIALOGS
    # ==========================================================================

    def show_settings(self):
        """
        Show the general settings dialog.
        
        This dialog allows users to configure:
        - System tray behavior (what happens on minimize/close)
        
        The dialog is modal (transient) and centered on the parent window.
        Changes are only saved when the user clicks "Save".
        """
        settings_window = customtkinter.CTkToplevel(self)
        # Track this window so it can be disabled during refresh
        self.settings_window = settings_window
        settings_window.title("Settings")
        settings_window.resizable(False, False)
        settings_window.transient(self)  # Make dialog modal
        settings_window.grab_set()       # Block interaction with parent
        self._center_dialog_on_parent(settings_window, self, 460, 420)
        # Clear reference when window is destroyed
        settings_window.bind('<Destroy>', lambda e: setattr(self, 'settings_window', None))
        
        frame = customtkinter.CTkFrame(settings_window)
        frame.pack(fill="both", expand=True, padx=self.ui.size(20), pady=self.ui.size(20))
        
        label = customtkinter.CTkLabel(frame, text="⚙️ Tray Settings", font=self.ui.font("Arial", 16, "bold"))
        label.pack(pady=(0, self.ui.size(10)))
        
        # ----------------------------------------------------------------------
        # SYSTEM TRAY BEHAVIOR OPTIONS
        # ----------------------------------------------------------------------
        
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
        
        # Get current setting (default to normal Windows behavior)
        tray_on = self.settings.get("tray_on", "none")
        # Store original value to restore on cancel
        original_tray_on = tray_on
        self.tray_radio_var = customtkinter.StringVar(value=tray_on)
        
        # Radio button options for tray behavior
        # "none" - Normal Windows behavior (close = exit, minimize = taskbar)
        none_radio = customtkinter.CTkRadioButton(
            tray_frame,
            text="Normal Windows behavior (no system tray)",
            variable=self.tray_radio_var,
            value="none"
        )
        none_radio.pack(anchor="w", pady=3, padx=5)

        # "close" - Close button minimizes to tray instead of exiting
        close_radio = customtkinter.CTkRadioButton(
            tray_frame,
            text="When I click Close (X) → Hide to tray (keep running)",
            variable=self.tray_radio_var,
            value="close"
        )
        close_radio.pack(anchor="w", pady=3, padx=5)
        
        # "minimize" - Minimize button hides to tray instead of taskbar
        minimize_radio = customtkinter.CTkRadioButton(
            tray_frame,
            text="When I click Minimize (_) → Hide to tray (keep running)",
            variable=self.tray_radio_var,
            value="minimize"
        )
        minimize_radio.pack(anchor="w", pady=3, padx=5) 
        
        # "both" - Both close and minimize hide to tray
        both_radio = customtkinter.CTkRadioButton(
            tray_frame,
            text="Both Close and Minimize → Hide to tray (keep running)",
            variable=self.tray_radio_var,
            value="both"
        )
        both_radio.pack(anchor="w", pady=3, padx=5)
        
        # Helpful note in highlighted box
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

        # ----------------------------------------------------------------------
        # SAVE / CANCEL BUTTONS
        # ----------------------------------------------------------------------
        
        btn_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(self.ui.size(12), 0))

        def save_and_apply_settings():
            """Save settings and close dialog."""
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

        # Center the buttons
        center_frame = customtkinter.CTkFrame(btn_frame, fg_color="transparent")
        center_frame.pack(anchor="center")

        def cancel_settings():
            """Cancel changes and close dialog."""
            # Restore original value (no changes saved)
            self.tray_radio_var.set(original_tray_on)
            settings_window.destroy()

        cancel_btn = customtkinter.CTkButton(
            center_frame,
            text="Cancel",
            command=cancel_settings,
            height=self.ui.size(36),
            width=self.ui.size(110),
            fg_color=("#D32F2F", "#C62828"),
            hover_color=("#C62828", "#B71C1C")
        )
        cancel_btn.pack(side="left", padx=self.ui.size(8))

        save_btn = customtkinter.CTkButton(center_frame, text="Save", command=save_and_apply_settings, height=self.ui.size(36), width=self.ui.size(110))
        save_btn.pack(side="left", padx=self.ui.size(8))

    def show_theme_settings(self):
        """
        Show the theme settings dialog.
        
        Allows users to choose between Dark, Light, and System themes.
        "System" follows the Windows light/dark mode setting automatically.
        """
        theme_window = customtkinter.CTkToplevel(self)
        # Track open theme dialog for disabling during refresh
        self.theme_window = theme_window
        theme_window.title("Theme Settings")
        theme_window.resizable(False, False)
        theme_window.transient(self)  # Make dialog modal
        theme_window.grab_set()       # Block interaction with parent
        self._center_dialog_on_parent(theme_window, self, 320, 260)
        theme_window.bind('<Destroy>', lambda e: setattr(self, 'theme_window', None))
        set_dark_title_bar(theme_window)  # Apply dark title bar if in dark mode
        
        frame = customtkinter.CTkFrame(theme_window)
        frame.pack(fill="both", expand=True, padx=self.ui.size(20), pady=self.ui.size(20))
        
        title = customtkinter.CTkLabel(frame, text="🎨 Application Theme", font=self.ui.font("Arial", 16, "bold"))
        title.pack(pady=(0, self.ui.size(20)))
        
        # Get current theme setting
        current_theme = self.settings.get("theme", "dark")
        theme_var = customtkinter.StringVar(value=current_theme)
        
        # Theme options with display labels
        theme_labels = {
            "dark": "Dark",
            "light": "Light",
            "system": "System (follow Windows)"  # Follows Windows accent color setting
        }
        
        # Create radio buttons for each theme option
        for theme in AVAILABLE_THEMES:
            theme_radio = customtkinter.CTkRadioButton(
                frame,
                text=theme_labels.get(theme, theme.capitalize()),
                variable=theme_var,
                value=theme,
                font=self.ui.font("Arial", 12)
            )
            theme_radio.pack(anchor="w", padx=self.ui.size(20), pady=self.ui.size(8))
        
        # Save / Cancel buttons
        btn_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(self.ui.size(12), 0))

        def apply_settings():
            """Apply the selected theme and close dialog."""
            self.settings["theme"] = theme_var.get()
            self.save_settings()
            self.apply_theme()
            self.status_label.configure(text="✅ Theme changed successfully")
            theme_window.destroy()

        # Center the buttons
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

    # ==========================================================================
    # EASTER EGG (Hidden Feature)
    # ==========================================================================

    def _on_title_click(self, event):
        """
        Handle clicks on the title label for easter egg activation.
        
        Tracks rapid consecutive clicks within a 0.4-second window. After 5 fast
        clicks, displays the hidden easter egg dialog and resets the counter.
        User must click continuously without stopping.
        
        Disabled during monitor refresh to prevent interference.
        """
        # Don't trigger easter egg while app is refreshing monitors
        if getattr(self, '_loading_monitors', False):
            return
        
        import time
        current_time = time.time()
        
        # Reset counter if more than 0.4 seconds since last click (must click rapidly)
        if current_time - self._easter_egg_last_click > 0.4:
            self._easter_egg_clicks = 0
        
        self._easter_egg_clicks += 1
        self._easter_egg_last_click = current_time
        
        # Trigger easter egg after 5 rapid clicks
        if self._easter_egg_clicks >= 5:
            self._easter_egg_clicks = 0
            self._show_easter_egg()

    def _show_easter_egg(self):
        """
        Display the hidden easter egg dialog.
        
        A fun surprise for users who discover the secret!
        Includes a real-time clock and countdown to the weekend.
        """
        from datetime import datetime, timedelta
        
        egg_window = customtkinter.CTkToplevel(self)
        egg_window.title("🥚🥚🥚")
        egg_window.resizable(False, False)
        egg_window.transient(self)
        egg_window.grab_set()
        self._center_dialog_on_parent(egg_window, self, 420, 420)
        
        # Apply dark title bar if in dark mode
        try:
            set_dark_title_bar(egg_window)
        except:
            pass
        
        frame = customtkinter.CTkFrame(egg_window)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Fun emoji header
        emoji_label = customtkinter.CTkLabel(
            frame,
            text="🎉🥚🎉",
            font=("Arial", 48)
        )
        emoji_label.pack(pady=(10, 10))
        
        # Easter egg message
        title_label = customtkinter.CTkLabel(
            frame,
            text="Bro, tkde kerja ke?!",
            font=("Arial", 18, "bold")
        )
        title_label.pack(pady=(0, 5))
        
        message_label = customtkinter.CTkLabel(
            frame,
            text="Anyway, CONGRATS--you made it to work today! 🐣\n\nThanks for using Monitor Manager.\nRemember, You're AWESOMEE!!! \nFrom, Budak Purple",
            font=("Arial", 12),
            justify="center"
        )
        message_label.pack(pady=(0, 15))
        
        # Separator
        separator = customtkinter.CTkFrame(frame, height=2, fg_color="#9B59B6")
        separator.pack(fill="x", pady=(0, 15))
        
        # Real-time clock display
        clock_label = customtkinter.CTkLabel(
            frame,
            text="",
            font=("Arial", 28, "bold"),
            text_color="#9B59B6"
        )
        clock_label.pack(pady=(0, 5))
        
        # Special weekday message label
        message_label = customtkinter.CTkLabel(
            frame,
            text="",
            font=("Arial", 14, "bold"),
            text_color="#888888"
        )
        message_label.pack(pady=(0, 5))
        
        # Countdown timer label (separate for different color)
        countdown_label = customtkinter.CTkLabel(
            frame,
            text="",
            font=("Arial", 14, "bold"),
            text_color="#888888"
        )
        countdown_label.pack(pady=(0, 15))
        
        # Track if window is still open for timer updates
        egg_window._is_open = True
        
        def update_clock():
            """Update the clock and countdown every second."""
            if not egg_window._is_open:
                return
            try:
                if not egg_window.winfo_exists():
                    return
            except:
                return
            
            now = datetime.now()
            
            # Update clock display
            time_str = now.strftime("%I:%M:%S %p")
            date_str = now.strftime("%A, %B %d, %Y")
            clock_label.configure(text=f"🕐 {time_str}")
            
            # Calculate countdown to weekend (Saturday 00:00:00)
            weekday = now.weekday()  # Monday=0, Sunday=6
            
            # Special messages for each weekday with unique colors (message color, countdown color)
            weekday_data = {
                0: ("😫 Ugh, Monday Biru ... Mengopi dulu!! ☕", "#3498DB", "#E67E22"),    # Monday - Blue msg, Orange countdown
                1: ("💪 Bilalah nak jumaat ni!! 🔥", "#E74C3C", "#1ABC9C"),               # Tuesday - Red msg, Teal countdown
                2: ("🐪 Ehh dah rabu dah, sikit je lagi!! 🎯", "#F39C12", "#3498DB"),    # Wednesday - Orange msg, Blue countdown
                3: ("⚡ Cantikk esok dah jumaat!! 🌟", "#9B59B6", "#F1C40F"),             # Thursday - Purple msg, Yellow countdown
                4: ("😎 Santaii esok dah cuti!! 🏖️", "#27AE60", "#27AE60"),              # Friday - Green (no countdown shown)
            }
            
            if weekday >= 5:  # Saturday (5) or Sunday (6)
                message_label.configure(text="🎉 IT'S THE WEEKEND! ENJOY! 🎉", text_color="#27AE60")
                countdown_label.configure(text="")
            else:
                # Days until Saturday
                days_until_saturday = 5 - weekday
                
                # Calculate exact time until Saturday 00:00:00
                next_saturday = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_until_saturday)
                time_remaining = next_saturday - now
                
                total_seconds = int(time_remaining.total_seconds())
                days = total_seconds // 86400
                hours = (total_seconds % 86400) // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                
                # Get the special message and colors for today
                special_msg, msg_color, timer_color = weekday_data.get(weekday, ("", "#E67E22", "#3498DB"))
                
                # Update message label with day's color
                message_label.configure(text=special_msg, text_color=msg_color)
                
                if weekday == 4:  # Friday - just show the message, no countdown
                    countdown_label.configure(text="")
                else:
                    # Show countdown with opposite color
                    if days > 0:
                        countdown_text = f"⏳ {days}d {hours}h {minutes}m {seconds}s until SABTU!!"
                    else:
                        countdown_text = f"⏳ {hours}h {minutes}m {seconds}s until SABTU!!"
                    
                    countdown_label.configure(text=countdown_text, text_color=timer_color)
            
            # Schedule next update in 1 second
            egg_window.after(1000, update_clock)
        
        def on_close():
            """Handle window close to stop the timer."""
            egg_window._is_open = False
            egg_window.destroy()
        
        egg_window.protocol("WM_DELETE_WINDOW", on_close)
        
        # Start the clock
        update_clock()
        
        # Close button
        close_btn = customtkinter.CTkButton(
            frame,
            text="✨ Pergi sambung kerja!! ✨",
            command=on_close,
            height=36,
            font=("Arial", 12, "bold"),
            fg_color="#9B59B6",
            hover_color="#8E44AD"
        )
        close_btn.pack(fill="x")

    # ==========================================================================
    # SYSTEM TRAY FUNCTIONALITY
    # ==========================================================================

    def update_tray_setting(self):
        """
        Update and persist the system tray behavior setting.
        
        Saves the current tray_radio_var value to settings and applies
        the new behavior immediately.
        """
        self.settings["tray_on"] = self.tray_radio_var.get()
        self.save_settings()
        self.update_tray_behavior()
        logging.info(f"Tray behavior set to: {self.settings['tray_on']}")
    
    def update_tray_behavior(self):
        """
        Apply window behavior changes based on tray_on setting.
        
        Reconfigures the window's close and minimize handlers based on
        the current tray setting:
        - "none": Normal Windows behavior (close exits, minimize to taskbar)
        - "close": Close button hides to tray
        - "minimize": Minimize button hides to tray
        - "both": Both close and minimize hide to tray
        """
        # Default to normal window behavior (no system tray)
        tray_on = self.settings.get("tray_on", "none")
        
        # Update close button behavior
        if tray_on in ["close", "both"]:
            # Close button hides to tray instead of exiting
            self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        else:
            # Close button exits the application
            self.protocol("WM_DELETE_WINDOW", self.quit_app)
        
        # Update minimize behavior binding
        try:
            self.unbind("<Unmap>")  # Remove existing binding
        except:
            pass
        
        if tray_on in ["minimize", "both"]:
            # Minimize button hides to tray instead of taskbar
            self.bind("<Unmap>", self.on_minimize)
    
    def create_tray_icon_image(self):
        """
        Create a simple icon image for the system tray.
        
        Draws a 64x64 pixel icon depicting a monitor shape.
        The icon is white background with black monitor outline.
        
        Returns:
            PIL.Image: The generated icon image
        """
        # Create a 64x64 white background image
        width = 64
        height = 64
        image = Image.new('RGB', (width, height), 'white')
        dc = ImageDraw.Draw(image)
        
        # Draw a simple monitor shape
        # Monitor screen (outer rectangle)
        dc.rectangle([10, 10, 54, 40], fill='black', outline='black')
        # Monitor screen (inner white area)
        dc.rectangle([12, 12, 52, 38], fill='white', outline='white')
        # Monitor stand (neck)
        dc.rectangle([28, 40, 36, 48], fill='black', outline='black')
        # Monitor stand (base)
        dc.rectangle([20, 48, 44, 52], fill='black', outline='black')
        
        return image
    
    def minimize_to_tray(self):
        """
        Hide the window to the system tray.
        
        Withdraws the window from view and creates a system tray icon
        if one doesn't already exist. The tray icon provides a menu
        to show the window or quit the application.
        """
        self.withdraw()  # Hide the window from taskbar and screen
        
        if self.tray_icon is None:
            # Create tray icon with context menu
            icon_image = self.create_tray_icon_image()
            menu = Menu(
                MenuItem('Show', self.show_window),   # Show the main window
                MenuItem('Quit', self.quit_app)       # Exit the application
            )
            self.tray_icon = Icon("Monitor Manager", icon_image, "Monitor Input Switcher", menu)
            
            # Run tray icon in a separate daemon thread
            # daemon=True ensures the thread terminates when the main app exits
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
    
    def on_minimize(self, event):
        """
        Handle window minimize event based on tray settings.
        
        This event handler is bound to the <Unmap> event which fires
        when the window is minimized (iconified). If tray settings
        allow, the window is hidden to tray instead of taskbar.
        
        Args:
            event: Tkinter event object
        """
        # Check if the window state changed to iconic (minimized)
        if event.widget == self and self.state() == 'iconic':
            # Only minimize to tray if setting allows it
            tray_on = self.settings.get("tray_on", "none")
            if tray_on in ["minimize", "both"]:
                # Use after() to avoid issues with event handling
                self.after(10, self.minimize_to_tray)
    
    def _on_window_configure(self, event):
        """
        Handle window configuration changes (move, resize).
        
        This event handler detects when the window is moved to a different
        position, which might indicate it was moved to a different monitor
        with different DPI settings.
        
        Args:
            event: Tkinter Configure event object
        """
        # Only process events for the main window, not child widgets
        if event.widget != self:
            return
        
        # Check if window position changed significantly (more than 50 pixels)
        # This threshold helps detect monitor changes while ignoring small movements
        x, y = self.winfo_x(), self.winfo_y()
        if abs(x - self._last_x) > 50 or abs(y - self._last_y) > 50:
            self._last_x, self._last_y = x, y
            
            # Debounce DPI check to avoid excessive recalculations during drag
            if not self._dpi_check_scheduled:
                self._dpi_check_scheduled = True
                # Check DPI after 500ms delay to allow window to settle
                self.after(500, self._check_and_apply_dpi_change)
    
    def _check_and_apply_dpi_change(self):
        """
        Check if DPI changed and re-apply scaling if needed.
        
        Called after a debounce delay when the window position changes.
        If the window moved to a monitor with different DPI, updates
        the UI scaling to match the new display.
        """
        self._dpi_check_scheduled = False
        
        if self.ui.check_dpi_change():
            # DPI changed - update CustomTkinter's scaling
            logging.info(f"DPI change detected. New scale: {self.ui.scale:.2f}")
            customtkinter.set_widget_scaling(self.ui.scale)
            customtkinter.set_window_scaling(self.ui.scale)
            
            # Update status to inform user
            self.status_label.configure(text=f"🖥️ Display scaling updated ({self.ui.scale:.0%})")
    
    def show_window(self, icon=None, item=None):
        """
        Show the main window from system tray.
        
        Called from the tray icon's context menu. Restores the window
        to visible state and brings it to the front.
        
        Args:
            icon: pystray Icon object (unused, required for callback signature)
            item: pystray MenuItem object (unused, required for callback signature)
        """
        self.deiconify()   # Show the window
        self.lift()        # Bring to front of other windows
        self.focus_force() # Give keyboard focus
    
    def quit_app(self, icon=None, item=None):
        """
        Quit the application completely.
        
        Stops the tray icon if running and destroys the main window.
        Sets is_quitting flag to prevent minimize_to_tray from running.
        
        Args:
            icon: pystray Icon object (unused, required for callback signature)
            item: pystray MenuItem object (unused, required for callback signature)
        """
        self.is_quitting = True
        if self.tray_icon:
            self.tray_icon.stop()  # Stop the tray icon thread
        self.quit()     # Exit Tkinter mainloop
        self.destroy()  # Destroy the window

    # ==========================================================================
    # FAVORITES MANAGEMENT DIALOG
    # ==========================================================================

    def show_manage_favorites(self):
        """
        Show the manage favorites dialog.
        
        This dialog allows users to:
        - View all saved favorites with their monitor/input mappings
        - Edit existing favorites (rename, change monitor, change input)
        - Delete favorites
        - Add new favorites
        
        The favorites list dynamically resizes based on the number of items.
        """
        manage_window = customtkinter.CTkToplevel(self)
        # Track this window for temporary disabling during refresh
        self.manage_window = manage_window
        manage_window.title("Manage Favorites")
        manage_window.resizable(False, False)
        manage_window.transient(self)  # Make dialog modal
        manage_window.grab_set()       # Block interaction with parent
        self._center_dialog_on_parent(manage_window, self, 450, 500)
        manage_window.bind('<Destroy>', lambda e: setattr(self, 'manage_window', None))
        
        main_frame = customtkinter.CTkFrame(manage_window)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        title = customtkinter.CTkLabel(main_frame, text="⭐ Manage Favorite Setups", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 15))
        
        # ----------------------------------------------------------------------
        # CURRENT FAVORITES SECTION
        # ----------------------------------------------------------------------
        
        # Section frame with dynamic sizing based on number of favorites
        fav_section = customtkinter.CTkFrame(main_frame)
        fav_section.pack(fill="x", expand=False, pady=(0, 15))
        
        fav_header = customtkinter.CTkLabel(fav_section, text="Current Favorites:", font=("Arial", 12, "bold"))
        fav_header.pack(anchor="w", padx=12, pady=(12, 8))
        
        # Frame for favorites list (height adjusts dynamically)
        favorites_list_frame = customtkinter.CTkFrame(fav_section, height=60)
        favorites_list_frame.pack(fill="x", expand=False, padx=12, pady=(0, 12))
        favorites_list_frame.pack_propagate(False)
        
        def update_favorites_list():
            """Rebuild the favorites list display."""
            # Clear existing items
            for widget in favorites_list_frame.winfo_children():
                widget.destroy()
            
            if not self.favorites:
                # Show placeholder when no favorites exist
                empty_label = customtkinter.CTkLabel(favorites_list_frame, text="No favorites saved yet.", text_color="gray")
                empty_label.pack(pady=20)
                favorites_list_frame.configure(height=60)
            else:
                # Calculate height based on number of favorites (each item ~45px)
                num_favorites = len(self.favorites)
                new_height = min(60 + (num_favorites * 45), 250)  # Cap at 250px
                favorites_list_frame.configure(height=new_height)
                
                # Create a row for each favorite
                for fav_name, (monitor_id, input_source) in self.favorites.items():
                    fav_frame = customtkinter.CTkFrame(favorites_list_frame)
                    fav_frame.pack(fill="x", pady=3)
                    
                    # Get monitor display name
                    try:
                        mon = next((m for m in self.monitors_data if m.get('id') == monitor_id), None)
                        display_name = mon.get('display_name', f"Monitor {monitor_id}") if mon else f"Monitor {monitor_id}"
                    except Exception:
                        display_name = f"Monitor {monitor_id}"
                    
                    # Label showing: FavoriteName: MonitorName → InputSource
                    label_text = f"{fav_name}: {display_name} → {input_source}"
                    label = customtkinter.CTkLabel(fav_frame, text=label_text, font=("Arial", 11))
                    label.pack(side="left", padx=8, pady=6)

                    # Delete button (red)
                    delete_btn = customtkinter.CTkButton(
                        fav_frame, text="Delete", width=70, height=28,
                        command=lambda n=fav_name: delete_favorite(n),
                        fg_color=("#D32F2F", "#C62828"),
                        hover_color=("#C62828", "#B71C1C")
                    )
                    delete_btn.pack(side="right", padx=8)

                    # Edit button (blue)
                    edit_btn = customtkinter.CTkButton(
                        fav_frame, text="Edit", width=70, height=28,
                        command=lambda n=fav_name: edit_favorite(n),
                        fg_color=("#1976D2", "#1565C0"),
                        hover_color=("#1565C0", "#0D47A1")
                    )
                    edit_btn.pack(side="right", padx=8)
            
            # Dynamically adjust window height based on content
            manage_window.update_idletasks()
            required_height = main_frame.winfo_reqheight() + 30
            manage_window.geometry(f"480x{required_height}")
        
        def delete_favorite(name):
            """Delete a favorite after confirmation."""
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
            """
            Open an edit dialog to modify a favorite's name, monitor, or input.
            
            Uses helper methods to reduce code duplication with the add favorite form.
            """
            current = self.favorites.get(name)
            if not current:
                messagebox.showerror("Error", f"Favorite '{name}' not found", parent=manage_window)
                return

            try:
                monitor_id, input_source = current
            except Exception:
                monitor_id, input_source = 0, "HDMI1"

            # Create edit dialog
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

    # ==========================================================================
    # SHORTCUTS EDITOR DIALOG
    # ==========================================================================

    def show_shortcuts_editor(self):
        """
        Show the keyboard shortcuts editor dialog.
        
        This dialog allows users to:
        - View all registered global keyboard shortcuts
        - Add new shortcuts by recording key combinations
        - Edit existing shortcuts (change key, monitor, or input)
        - Delete shortcuts
        
        Global hotkeys work even when the application is minimized or in
        the background. They are registered using the 'keyboard' library.
        
        Note: The record_shortcut() function uses a keyboard hook that must
        be properly cleaned up to prevent memory leaks (FIX #3).
        """
        editor_window = customtkinter.CTkToplevel(self)
        # Track this editor window so it can be disabled during refresh
        self.editor_window = editor_window
        editor_window.title("Keyboard Shortcuts")
        editor_window.resizable(False, False)
        editor_window.transient(self)  # Make dialog modal
        editor_window.grab_set()       # Block interaction with parent
        self._center_dialog_on_parent(editor_window, self, 520, 600)
        editor_window.bind('<Destroy>', lambda e: setattr(self, 'editor_window', None))
        
        main_frame = customtkinter.CTkFrame(editor_window)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        title = customtkinter.CTkLabel(main_frame, text="⌨️ Keyboard Shortcuts", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 10))
        
        # ----------------------------------------------------------------------
        # DISCLAIMER/HELP SECTION
        # ----------------------------------------------------------------------
        # Explains that global hotkeys work system-wide
        
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

        # ----------------------------------------------------------------------
        # CURRENT SHORTCUTS LIST SECTION
        # ----------------------------------------------------------------------
        
        shortcuts_section = customtkinter.CTkFrame(main_frame)
        shortcuts_section.pack(fill="both", expand=True, pady=(0, 15))
        
        shortcuts_header = customtkinter.CTkLabel(shortcuts_section, text="Current Shortcuts:", font=("Arial", 13, "bold"))
        shortcuts_header.pack(anchor="w", padx=12, pady=(12, 8))
        
        # Scrollable frame to handle many shortcuts
        shortcuts_frame = customtkinter.CTkScrollableFrame(shortcuts_section, height=320)
        shortcuts_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        
        def update_shortcuts_list():
            """Rebuild the shortcuts list display."""
            # Clear existing items
            for widget in shortcuts_frame.winfo_children():
                widget.destroy()
                
            monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else []
            shown = 0
            
            # Display each shortcut as a row
            for shortcut, (monitor_id, input_source) in self.shortcuts.items():
                # Only show shortcuts for currently connected monitors
                mon = next((m for m in monitors_list if m.get('id') == monitor_id), None)
                if not mon:
                    continue

                shown += 1
                shortcut_frame = customtkinter.CTkFrame(shortcuts_frame)
                shortcut_frame.pack(fill="x", pady=3)

                # Display: "ctrl+alt+1: Samsung - C27G2 → HDMI1"
                display_name = mon.get('display_name', f"Monitor {monitor_id}")
                label = customtkinter.CTkLabel(
                    shortcut_frame,
                    text=f"{shortcut}: {display_name} → {input_source}",
                    font=("Arial", 12),
                    wraplength=420
                )
                label.pack(side="left", padx=8, pady=6) 

                # Edit/Delete buttons on the right
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

            # Show notice if no shortcuts are configured for connected monitors
            if shown == 0:
                notice = customtkinter.CTkLabel(shortcuts_frame, text="No shortcuts for currently connected monitors.", text_color="gray")
                notice.pack(pady=20)

        def record_shortcut(callback):
            """
            Open a dialog to record a keyboard shortcut.
            
            Captures the key combination the user presses and passes it
            to the callback function. Handles modifier keys (ctrl, alt, shift)
            and regular keys.
            
            FIX #3: Properly cleans up keyboard hook on dialog close.
            
            Args:
                callback: Function to call with the recorded shortcut string
            """
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
            # Use list to allow modification in nested function
            hook_handle = [None]
            
            # Map of shifted characters to their base number keys
            # e.g., Shift+2 produces '@', but we want to record as 'shift+2'
            char_to_key = {
                '@': '2', '!': '1', '#': '3', '$': '4', '%': '5',
                '^': '6', '&': '7', '*': '8', '(': '9', ')': '0'
            }
            
            def cleanup_hook():
                """Remove the keyboard hook to prevent memory leaks."""
                if hook_handle[0] is not None:
                    try:
                        keyboard.unhook(hook_handle[0])
                    except Exception:
                        pass
                    hook_handle[0] = None
            
            def on_key(event):
                """Handle key press event during recording."""
                # Skip if this is just a modifier key press
                if event.name not in recorded_keys and event.name not in ['ctrl', 'alt', 'shift']:
                    # Add pressed modifiers first
                    recorded_keys.extend(k for k in ['ctrl', 'alt', 'shift'] if keyboard.is_pressed(k))
                    
                    # Map shifted characters back to their base keys
                    key_name = char_to_key.get(event.name, event.name)
                    recorded_keys.append(key_name)
                    
                    shortcut = '+'.join(recorded_keys)
                    label.configure(text=f"Recorded: {shortcut}\n\nPress ENTER to confirm or ESC to cancel")
                    
                    # Handle confirmation or cancellation
                    if event.name == 'enter':
                        cleanup_hook()
                        dialog.destroy()
                        # Pass shortcut without the final 'enter' key
                        callback('+'.join(recorded_keys[:-1]))
                    elif event.name == 'esc':
                        cleanup_hook()
                        dialog.destroy()
            
            # Register keyboard hook for key press events
            hook_handle[0] = keyboard.on_press(on_key)
            
            # FIX #3: Also cleanup if user closes dialog via window X button
            dialog.protocol("WM_DELETE_WINDOW", lambda: (cleanup_hook(), dialog.destroy()))
            
        def add_new_shortcut():
            """Start the process of adding a new shortcut."""
            def on_shortcut(shortcut):
                """Handle recorded shortcut and show monitor/input selection."""
                if shortcut:
                    # Create configuration dialog for this shortcut
                    select_dialog = customtkinter.CTkToplevel(editor_window)
                    select_dialog.title("Configure Shortcut")
                    select_dialog.transient(editor_window)
                    select_dialog.grab_set()
                    self._center_dialog_on_parent(select_dialog, editor_window, 400, 280)
                    set_dark_title_bar(select_dialog)

                    frame = customtkinter.CTkFrame(select_dialog)
                    frame.pack(fill="both", expand=True, padx=20, pady=20)

                    title = customtkinter.CTkLabel(frame, text=f"Shortcut: {shortcut}", font=("Arial", 13, "bold"))
                    title.pack(pady=(0, 15))

                    # Build monitor choices list
                    monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else []
                    mon_choices = [f"{m.get('id')}: {m.get('display_name')}" for m in monitors_list] if monitors_list else ["0"]

                    mon_label = customtkinter.CTkLabel(frame, text="Select Monitor:", font=("Arial", 11))
                    mon_label.pack(anchor="w", pady=(0, 5))

                    mon_var = customtkinter.StringVar(value=mon_choices[0])
                    mon_menu = customtkinter.CTkOptionMenu(frame, variable=mon_var, values=mon_choices, height=32)
                    mon_menu.pack(fill="x", pady=(0, 15))

                    input_label = customtkinter.CTkLabel(frame, text="Select Input:", font=("Arial", 11))
                    input_label.pack(anchor="w", pady=(0, 5))

                    # Get initial inputs for first monitor
                    initial_inputs = monitors_list[0].get('inputs', []) if monitors_list else ["HDMI1", "DP1"]
                    input_var = customtkinter.StringVar(value=initial_inputs[0] if initial_inputs else "HDMI1")
                    input_menu = customtkinter.CTkOptionMenu(frame, variable=input_var, values=initial_inputs, height=32)
                    input_menu.pack(fill="x", pady=(0, 20))

                    def save():
                        """Save the new shortcut configuration."""
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
                        """Update input choices when monitor selection changes."""
                        sel = mon_var.get()
                        try:
                            sel_id = int(sel.split(':', 1)[0].strip()) if ':' in sel else int(sel)
                        except Exception:
                            return
                        
                        # Find inputs for selected monitor
                        inputs_for_sel = []
                        for mon in monitors_list:
                            if mon.get('id') == sel_id:
                                inputs_for_sel = mon.get('inputs', []) or []
                                break
                        
                        # Fallback to common inputs if none detected
                        if not inputs_for_sel:
                            inputs_for_sel = ["DP1", "HDMI1", "DP2", "HDMI2"]
                        
                        input_menu.configure(values=inputs_for_sel)
                        input_var.set(inputs_for_sel[0])

                    mon_var.trace_add('write', update_input_options)
                    update_input_options()
            
            # Start by recording the shortcut
            record_shortcut(on_shortcut)
            
        def edit_shortcut(shortcut):
            """
            Edit an existing shortcut.
            
            Allows changing both the key combination and the monitor/input
            configuration for an existing shortcut.
            
            Args:
                shortcut: The current shortcut key string to edit
            """
            current_monitor_id, current_input = self.shortcuts.get(shortcut, (0, "HDMI1"))
            
            edit_dialog = customtkinter.CTkToplevel(editor_window)
            edit_dialog.title("Edit Shortcut")
            edit_dialog.transient(editor_window)
            edit_dialog.grab_set()
            self._center_dialog_on_parent(edit_dialog, editor_window, 400, 350)
            set_dark_title_bar(edit_dialog)
            
            frame = customtkinter.CTkFrame(edit_dialog)
            frame.pack(fill="both", expand=True, padx=20, pady=20)
            
            # Current shortcut display with change button
            shortcut_var = customtkinter.StringVar(value=shortcut)
            shortcut_label = customtkinter.CTkLabel(frame, text="Shortcut Key:", font=("Arial", 11))
            shortcut_label.pack(anchor="w", pady=(0, 5))
            
            shortcut_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
            shortcut_frame.pack(fill="x", pady=(0, 15))
            
            shortcut_display = customtkinter.CTkLabel(shortcut_frame, textvariable=shortcut_var, font=("Arial", 13, "bold"))
            shortcut_display.pack(side="left", padx=(0, 10))
            
            def change_key():
                """Record a new key combination for this shortcut."""
                def on_new_key(new_key):
                    if new_key:
                        shortcut_var.set(new_key)
                record_shortcut(on_new_key)
            
            change_key_btn = customtkinter.CTkButton(shortcut_frame, text="Change Key", command=change_key, width=100, height=28)
            change_key_btn.pack(side="left")
            
            # Monitor selection
            monitors_list = self.monitors_data if hasattr(self, 'monitors_data') and self.monitors_data else []
            mon_choices = [f"{m.get('id')}: {m.get('display_name')}" for m in monitors_list] if monitors_list else ["0"]
            
            # Find the current monitor choice to pre-select
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
            
            # Get inputs for current monitor
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
                """Update input choices when monitor selection changes."""
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
                """Save the edited shortcut configuration."""
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
            """
            Delete a shortcut after user confirmation.
            
            Removes the shortcut from the dictionary, saves to disk,
            and re-registers all remaining hotkeys.
            
            Args:
                shortcut: The shortcut key string to delete
            """
            try:
                try:
                    confirm = messagebox.askyesno("Confirm Delete", f"Delete shortcut '{shortcut}'?", parent=editor_window)
                except Exception:
                    confirm = True

                if not confirm:
                    return

                # Remove from shortcuts dictionary
                self.shortcuts.pop(shortcut)
                self.save_shortcuts()
                
                # Re-register all remaining hotkeys
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
        
        # ----------------------------------------------------------------------
        # ADD NEW SHORTCUT BUTTON
        # ----------------------------------------------------------------------
        
        buttons_frame = customtkinter.CTkFrame(main_frame, fg_color="transparent")
        buttons_frame.pack(fill="x")
        
        add_button = customtkinter.CTkButton(buttons_frame, text="➕ Add New Shortcut", command=add_new_shortcut, height=36, font=("Arial", 12, "bold"), fg_color="#28a745", hover_color="#218838")
        add_button.pack(fill="x")
        
        # Initial population of the shortcuts list
        update_shortcuts_list()

    # ==========================================================================
    # SHORTCUTS HELP DIALOG
    # ==========================================================================

    def show_shortcuts_help(self):
        """
        Show the keyboard shortcuts help dialog.
        
        Displays all registered shortcuts in a scrollable list.
        This dialog is triggered by pressing Ctrl+Shift+H globally.
        Provides a button to open the full shortcuts editor.
        """
        help_window = customtkinter.CTkToplevel(self)
        help_window.title("Keyboard Shortcuts Help")
        help_window.transient(self)  # Make dialog modal
        help_window.grab_set()       # Block interaction with parent
        self._center_dialog_on_parent(help_window, self, 450, 400)
        
        # Scrollable frame for shortcuts list
        frame = customtkinter.CTkScrollableFrame(help_window)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        title = customtkinter.CTkLabel(frame, text="⌨️ Available Shortcuts", font=("Arial", 16, "bold"))
        title.pack(pady=(0, 15))
        
        # Display each registered shortcut
        for shortcut, (monitor_id, input_source) in self.shortcuts.items():
            text = f"{shortcut}: Switch Monitor {monitor_id} to {input_source}"
            label = customtkinter.CTkLabel(frame, text=text, font=("Arial", 11))
            label.pack(anchor="w", pady=3)
        
        # Show the built-in help shortcut
        help_shortcut = customtkinter.CTkLabel(frame, text="\nctrl+shift+h: Show this help window", font=("Arial", 11, "bold"))
        help_shortcut.pack(anchor="w", pady=(15, 3))
        
        # Button to open full shortcuts editor
        customize_btn = customtkinter.CTkButton(
            frame,
            text="Customize Shortcuts",
            command=lambda: [help_window.destroy(), self.show_shortcuts_editor()],
            height=36,
            font=("Arial", 12, "bold")
        )
        customize_btn.pack(pady=(20, 0), fill="x")


# ==============================================================================
# STANDALONE UTILITY FUNCTIONS
# ==============================================================================
# These functions operate independently of the App class and are used for
# CLI mode operation and input code translation.

def get_input_name(code):
    """
    Convert a DDC/CI input source code to a human-readable name.
    
    The DDC/CI standard defines numeric codes for different video input sources.
    This function maps those codes to recognizable names like "HDMI1" or "USB-C".
    
    Args:
        code: Integer VCP code for the input source (0-27 typically)
        
    Returns:
        str: Human-readable name of the input source, or "UNKNOWN CODE X" if not recognized
        
    Example:
        >>> get_input_name(17)
        'HDMI1'
        >>> get_input_name(27)
        'USB-C'
    """
    # Standard InputSource enum mapping based on DDC/CI specification
    # VCP_INPUT_THUNDERBOLT (26) and VCP_INPUT_USB_C (27) are custom additions
    standard_inputs = {
        0: "NO INPUT",
        1: "VGA1",         # Changed from ANALOG1/VGA for clarity
        2: "VGA2",         # Changed from ANALOG2 for clarity
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
        15: "DP1",         # DisplayPort 1
        16: "DP2",         # DisplayPort 2
        17: "HDMI1",
        18: "HDMI2",
        VCP_INPUT_THUNDERBOLT: "THUNDERBOLT",  # Code 26
        VCP_INPUT_USB_C: "USB-C"               # Code 27
    }
    
    return standard_inputs.get(code, f"UNKNOWN CODE {code}")


def cli_switch_input(monitor_index, input_name):
    """
    Switch a monitor's input source via command line interface.
    
    This function is used when the application is run in CLI mode
    (with --monitor and --input arguments). It allows headless
    operation without launching the GUI.
    
    Args:
        monitor_index: Zero-based index of the monitor to switch
        input_name: Name of the input source (e.g., "HDMI1", "DP1", "USB_C")
                    Must match an attribute name in the InputSource enum
                    
    Returns:
        bool: True if successfully switched, False on error
        
    Example:
        # From command line:
        # monitor_manager.exe --monitor 0 --input HDMI1
        
    Note:
        FIX #2: Gets monitors fresh for CLI mode (not using global variable)
        to ensure we have current monitor list.
    """
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
            # Validate the input name exists in InputSource enum
            if not hasattr(InputSource, input_name):
                print(f"Error: Invalid input source: {input_name}")
                print("Available inputs: " + ", ".join([x for x in dir(InputSource) if not x.startswith('_')]))
                return False

            # Get the enum value and send DDC/CI command
            new_input = getattr(InputSource, input_name)
            monitor.set_input_source(new_input)
            print(f"Successfully switched monitor {monitor_index} to {input_name}")
            return True

    except Exception as e:
        print(f"Error: {e}")
        return False


def cli_list_monitors():
    """
    List all available monitors and their inputs via command line.
    
    This function is used when the application is run with the --list
    argument. It creates a temporary App instance to detect monitors
    and prints their information to stdout.
    
    Output format:
        Available Monitors:
        --------------------------------------------------
        Monitor 0: Samsung - C27G2
        Current Input: HDMI1
        Available Inputs: HDMI1, HDMI2, DP1
        --------------------------------------------------
        
    Note:
        Creates and immediately destroys an App instance to use
        the monitor detection logic, then prints results.
    """
    try:
        # Create temporary App instance for monitor detection
        app = App()
        monitors_data = app.get_all_monitor_data()
        app.destroy()  # Clean up the window

        if not monitors_data:
            print("No monitors found")
            return

        # Print formatted monitor information
        print("\nAvailable Monitors:")
        print("-" * 50)
        for monitor in monitors_data:
            print(f"Monitor {monitor['id']}: {monitor['display_name']}")
            print(f"Current Input: {monitor['current_input']}")
            print(f"Available Inputs: {', '.join(monitor['inputs'])}")
            print("-" * 50)

    except Exception as e:
        print(f"Error: {e}")


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================

if __name__ == "__main__":
    """
    Application entry point.
    
    Supports two modes of operation:
    
    1. GUI Mode (default):
       Simply run the application to launch the graphical interface.
       Example: monitor_manager.exe
    
    2. CLI Mode:
       Use command line arguments for headless operation.
       
       --list              List all monitors and their available inputs
       --monitor N         Specify monitor index (0-based) to control
       --input NAME        Specify input source name (e.g., HDMI1, DP1)
       
       Examples:
         monitor_manager.exe --list
         monitor_manager.exe --monitor 0 --input HDMI1
         monitor_manager.exe --monitor 1 --input DP1
    
    The application logs critical errors to the log file for debugging.
    """
    try:
        import argparse
        
        # Set up command line argument parser
        parser = argparse.ArgumentParser(description='Monitor Input Switcher')
        
        # CLI mode arguments
        parser.add_argument('--cli', action='store_true', help='Run in CLI mode')
        parser.add_argument('--list', action='store_true', help='List all monitors and their inputs')
        parser.add_argument('--monitor', type=int, help='Monitor index to control')
        parser.add_argument('--input', type=str, help='Input source to switch to (e.g., HDMI1, DP1)')
        
        args = parser.parse_args()

        # Check if any CLI arguments were provided
        if args.cli or args.list or args.monitor is not None or args.input is not None:
            # CLI mode - run without GUI
            if args.list:
                # List all monitors and exit
                cli_list_monitors()
            elif args.monitor is not None and args.input is not None:
                # Switch specific monitor to specific input
                cli_switch_input(args.monitor, args.input)
            else:
                # Invalid combination of arguments
                print("Error: For CLI mode, use either --list to list monitors,")
                print("or both --monitor and --input to switch inputs.")
                print("\nExample usage:")
                print("  monitor_manager.exe --list")
                print("  monitor_manager.exe --monitor 0 --input HDMI1")
        else:
            # GUI mode - launch the application window
            app = App()
            app.mainloop()  # Start Tkinter event loop
            
    except Exception as e:
        # Log any unhandled exceptions
        logging.critical(f"Unhandled exception: {e}", exc_info=True)
        print(f"Critical error: {e}")