import obd
import customtkinter as ctk
import threading

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class OBDWorkshop(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("OBD2 Professional Workshop Tool")
        self.geometry("1000x700")

        self.connection = None
        
        # --- UI LAYOUT ---
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar for Connection & Actions
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        self.logo_label = ctk.CTkLabel(self.sidebar, text="ECU MASTER", font=("Consolas", 24, "bold"))
        self.logo_label.pack(pady=20)

        self.btn_scan = ctk.CTkButton(self.sidebar, text="Scan Ports", command=self.scan_ports)
        self.btn_scan.pack(pady=10, padx=20)

        self.port_combo = ctk.CTkComboBox(self.sidebar, values=["Select Port"])
        self.port_combo.pack(pady=10, padx=20)

        self.btn_connect = ctk.CTkButton(self.sidebar, text="Establish Connection", fg_color="green", command=self.connect_obd)
        self.btn_connect.pack(pady=10, padx=20)

        self.btn_dtc = ctk.CTkButton(self.sidebar, text="Read Error Codes (DTC)", state="disabled", command=self.read_dtcs)
        self.btn_dtc.pack(pady=40, padx=20)

        # Main Content Area
        self.main_content = ctk.CTkFrame(self, fg_color="transparent")
        self.main_content.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        # Top Bar - Vehicle Identity
        self.info_frame = ctk.CTkFrame(self.main_content, height=100)
        self.info_frame.pack(fill="x", pady=(0, 20))
        
        self.vin_display = ctk.CTkLabel(self.info_frame, text="VIN: NOT DETECTED", font=("Courier New", 18))
        self.vin_display.pack(pady=10)
        self.protocol_display = ctk.CTkLabel(self.info_frame, text="Protocol: Unknown", text_color="gray")
        self.protocol_display.pack()

        # Center - Critical Engine Data
        self.data_grid = ctk.CTkFrame(self.main_content)
        self.data_grid.pack(fill="both", expand=True)
        
        self.metrics = {}
        self.create_metric_card("Battery Voltage", "Control Module Voltage", "V")
        self.create_metric_card("Coolant Temp", "Engine Coolant Temperature", "°C")
        self.create_metric_card("Fuel Pressure", "Fuel Rail Pressure", "kPa")
        self.create_metric_card("Engine Load", "Calculated Load Value", "%")

        # Bottom - Terminal for Manual Commands
        self.terminal_frame = ctk.CTkFrame(self.main_content, height=200)
        self.terminal_frame.pack(fill="x", pady=(20, 0))
        
        self.terminal_output = ctk.CTkTextbox(self.terminal_frame, height=100, font=("Consolas", 12))
        self.terminal_output.pack(fill="x", padx=10, pady=5)
        
        self.command_entry = ctk.CTkEntry(self.terminal_frame, placeholder_text="Enter AT or HEX Command (e.g. 01 00)")
        self.command_entry.pack(side="left", fill="x", expand=True, padx=10, pady=5)
        
        self.btn_send = ctk.CTkButton(self.terminal_frame, text="Send", width=80, command=self.send_custom_command)
        self.btn_send.pack(side="right", padx=10)

    def create_metric_card(self, title, description, unit):
        card = ctk.CTkFrame(self.data_grid, width=300, height=120, border_width=1)
        card.pack(side="left", padx=10, pady=10, fill="y")
        
        ctk.CTkLabel(card, text=title, font=("Arial", 14, "bold")).pack(pady=5)
        val_lbl = ctk.CTkLabel(card, text="--", font=("Arial", 32, "bold"), text_color="#3b8ed0")
        val_lbl.pack()
        ctk.CTkLabel(card, text=f"{description} ({unit})", font=("Arial", 10), text_color="gray").pack()
        
        self.metrics[title] = val_lbl

    def scan_ports(self):
        import serial.tools.list_ports
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo.configure(values=ports)
        self.log("Scanned system for COM ports.")

    def log(self, text):
        self.terminal_output.insert("end", f"> {text}\n")
        self.terminal_output.see("end")

    def connect_obd(self):
        port = self.port_combo.get()
        self.log(f"Connecting to {port}...")
        
        threading.Thread(target=self._internal_connect, args=(port,), daemon=True).start()

    def _internal_connect(self, port):
        self.connection = obd.OBD(port)
        if self.connection.status() == obd.OBDStatus.CAR_CONNECTED:
            self.log("Connected Successfully!")
            self.btn_dtc.configure(state="normal")
            
            # Get Vehicle Info
            vin = self.connection.query(obd.commands.VIN)
            protocol = self.connection.protocol_name()
            
            self.vin_display.configure(text=f"VIN: {vin.value if not vin.is_null() else 'Unknown'}")
            self.protocol_display.configure(text=f"Protocol: {protocol}")
            
            self.start_monitoring()
        else:
            self.log("Connection Failed. Check ignition.")

    def start_monitoring(self):
        def update():
            if self.connection and self.connection.is_connected():
                # Map titles to OBD commands
                cmds = {
                    "Battery Voltage": obd.commands.ELM_VOLTAGE, # מתח מצבר מהצ'יפ
                    "Coolant Temp": obd.commands.COOLANT_TEMP,
                    "Fuel Pressure": obd.commands.FUEL_PRESSURE,
                    "Engine Load": obd.commands.ENGINE_LOAD
                }
                for title, cmd in cmds.items():
                    res = self.connection.query(cmd)
                    if not res.is_null():
                        self.metrics[title].configure(text=str(res.value.magnitude))
                
                self.after(1000, update)
        update()

    def read_dtcs(self):
        self.log("Scanning for Trouble Codes (DTCs)...")
        res = self.connection.query(obd.commands.GET_DTC)
        if not res.is_null():
            self.log(f"Codes Found: {res.value}")
        else:
            self.log("No Trouble Codes Found (System Clear).")

    def send_custom_command(self):
        cmd_str = self.command_entry.get()
        if self.connection and self.connection.is_connected():
            self.log(f"Sending RAW: {cmd_str}")
            # כאן שולחים פקודה ישירה למתאם
            response = self.connection.elmsend(cmd_str.encode())
            self.log(f"Response: {response}")

if __name__ == "__main__":
    app = OBDWorkshop()
    app.mainloop()
