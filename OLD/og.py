import customtkinter
from monitorcontrol import get_monitors, InputSource
import platform
import logging
import threading
import os
import sys
from screeninfo import get_monitors as get_screen_info

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

# Fallback for model names
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
    "XL": "BenQ", "EX": "BenQ", "PD": "BenQ", "EW": "BenQ", "ZOWIE": "BenQ", "GL": "BenQ",
    "XV": "Acer", "XF": "Acer", "KG": "Acer", "CB": "Acer", "XB": "Acer",
    "NITRO": "Acer", "PREDATOR": "Acer",
    "MAG": "MSI", "MPG": "MSI", "OPTIX": "MSI", "MEG": "MSI",
    "FI": "Gigabyte", "M": "Gigabyte", "G27": "Gigabyte", "AORUS": "Gigabyte",
    "OMEN": "HP", "X27": "HP", "Z27": "HP", "PAVILION": "HP",
    "BDM": "Philips", "PHL": "Philips", "PHI": "Philips"
}

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class App(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        self.title("Monitor Input Switcher")
        self.geometry("500x350") # Adjusted height
        self.iconbitmap(resource_path('monitor_manager_icon.ico')) # Set window icon

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

        self.status_label = customtkinter.CTkLabel(self, text="", wraplength=480)
        self.status_label.pack(pady=(0, 10), padx=20)

        # Name at the bottom
        self.name_label = customtkinter.CTkLabel(self, text="By: LuqmanHakimAmiruddin@PDC", font=("Arial", 10))
        self.name_label.pack(pady=(5, 10))

        self.refresh_monitors()

    def refresh_monitors(self):
        self.status_label.configure(text="Fetching all monitors info...")
        self.progress_bar.pack(pady=(10, 10), fill="x", padx=20)
        self.progress_bar.start()

        self.switch_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")

        # Set dropdowns to loading state
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
        else:
            self.monitor_menu.set("No monitors found")
            self.input_menu.configure(values=[])
            self.input_menu.set("")
            self.status_label.configure(text="No monitors found. Please check connections.")

        self.progress_bar.stop()
        self.progress_bar.pack_forget()

        self.switch_button.configure(state="normal")
        self.refresh_button.configure(state="normal")

    def get_all_monitor_data(self):
        all_data = []
        try:
            monitors = get_monitors()
            logging.info(f"Found {len(monitors)} monitors.")
        except Exception as e:
            logging.error(f"Could not get monitors: {e}")
            return []

        pnp_ids = []
        if platform.system() == "Windows":
            try:
                c = wmi.WMI()
                wmi_monitors = c.Win32_DesktopMonitor()
                for monitor in wmi_monitors:
                    pnp_id = getattr(monitor, 'PNPDeviceID', None)
                    pnp_ids.append(pnp_id)
                logging.info(f"WMI PnP IDs: {pnp_ids}")
            except Exception as e:
                logging.error(f"Failed to get PnP IDs from WMI: {e}")

        for i, monitor_obj in enumerate(get_monitors()):
            with monitor_obj:
                # Get Model
                try:
                    model = monitor_obj.get_vcp_capabilities()['model']
                    logging.info(f"{monitor_obj.get_vcp_capabilities()}")
                except Exception as e:
                    model = "Unknown"
                    logging.warning(f"Could not get model for monitor {i}: {e}")

                # Get Brand
                brand = "unknown"
                if i < len(pnp_ids) and pnp_ids[i] is not None:
                    try:
                        pnp_code = pnp_ids[i].split('\\')[1][:3]
                        brand = PNP_IDS.get(pnp_code, "Unknown")
                    except (IndexError, AttributeError):
                        logging.warning(f"Could not parse PnP ID: {pnp_ids[i]}")
                
                if brand == "Unknown" and model != "Unknown":
                    for prefix, brand_name in MODEL_BRAND_MAP.items():
                        if model.upper().startswith(prefix):
                            brand = brand_name
                            break

                # Get Inputs
                try:
                    input_names = []
                    inputs = monitor_obj.get_vcp_capabilities()['inputs']
                    for inp in inputs:
                        if hasattr(inp, 'name'):
                            input_names.append(inp.name)
                        elif isinstance(inp, int):
                            # USB-C with DisplayPort Alt Mode uses code 27 (0x1B)
                            # Thunderbolt also uses USB-C connector with DP protocol
                            if inp == 27:
                                input_names.append("USB-C")
                            elif inp == 26:
                                input_names.append("THUNDERBOLT")
                            else:
                                # Unknown input code - display as is for debugging
                                input_names.append(f"INPUT_{inp}")
                except (KeyError, TypeError):
                    input_names = ["DP1", "DP2", "HDMI1", "HDMI2"]

                # Get current input
                current_input = "Unknown"
                try:
                    current_input = monitor_obj.get_input_source()
                    if hasattr(current_input, 'value'):
                        current_code = current_input.value
                        current_name = current_input.name if hasattr(current_input, 'name') else str(current_input)
                    else:
                        current_code = int(current_input)
                        current_name = get_input_name(current_code)
                except Exception as e:
                    logging.warning(f"Could not get current input for monitor {i}: {e}")
                    current_code = None
                    current_name = "Unknown"
                    
                all_data.append({
                    "display_name": f"{brand} - {model}",
                    "inputs": input_names,
                    "id": i, # Store the index
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
            # Set the initial value to the current input source
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
            # ID of the monitor being switched
            selected_monitor_id = self.selected_monitor_data['id']
            all_screens = get_screen_info()

            if selected_monitor_id < len(all_screens):
                screen_to_switch = all_screens[selected_monitor_id]
                app_current_screen = self.get_current_screen()

                # If the app is on the screen we're about to switch, move it
                if app_current_screen and app_current_screen == screen_to_switch:
                    other_screens = [s for s in all_screens if s != screen_to_switch]
                    if other_screens:
                        new_screen = other_screens[0]
                        self.geometry(f"+{new_screen.x}+{new_screen.y}")
                        self.update_idletasks()  # Ensure the move is processed
            else:
                logging.warning("Selected monitor ID is out of range of available screens.")

            # Handle custom input codes (USB-C, Thunderbolt, etc.)
            if new_input_str == "USB-C":
                new_input = 27  # USB-C with DisplayPort Alt Mode
            elif new_input_str == "THUNDERBOLT":
                new_input = 26  # Thunderbolt
            elif new_input_str.startswith("INPUT_"):
                # Handle unknown input codes (INPUT_XX format)
                new_input = int(new_input_str.split('_')[1])
            else:
                # Standard InputSource enum values
                new_input = getattr(InputSource, new_input_str)

            # Get a fresh monitor object to be safe
            with get_monitors()[self.selected_monitor_data['id']] as monitor:
                monitor.set_input_source(new_input)
            self.status_label.configure(text=f"Successfully switched to {new_input_str}")
        except AttributeError:
            self.status_label.configure(text=f"Invalid input source: {new_input_str}")
        except Exception as e:
            self.status_label.configure(text=f"Error switching input: {e}")
            logging.error(f"Failed to switch input: {e}")

    def get_current_screen(self):
        self.update_idletasks()  # Make sure window info is up-to-date
        x, y = self.winfo_x(), self.winfo_y()
        for screen in get_screen_info():
            if screen.x <= x < screen.x + screen.width and screen.y <= y < screen.y + screen.height:
                return screen
        return None

def get_input_name(code):
    """Convert input code to readable name"""
    # Standard InputSource enum mapping
    standard_inputs = {
        0: "OFF",
        1: "ANALOG1",
        2: "ANALOG2",
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
        26: "THUNDERBOLT",
        27: "USB-C"
    }
    
    return standard_inputs.get(code, f"UNKNOWN CODE {code}")

if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    except Exception as e:
        logging.critical(f"Unhandled exception: {e}", exc_info=True)