import tkinter as tk
from tkinter import ttk
import ttkbootstrap as tb
import logging
import threading
import time
import asyncio
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusServerContext
from pymodbus.datastore.context import ModbusSlaveContext
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.device import ModbusDeviceIdentification

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                    handlers=[logging.FileHandler("plc_simulator.log"), logging.StreamHandler()])
logger = logging.getLogger('PLCSimulator')

# --- Register Map (MUST MATCH CLIENT) ---
REG_REF_NAME_START = 0
REF_NAME_LENGTH = 10
REG_CAM_ID = 10
REG_CYCLE_END = 11  # Not used by our client, but part of this PLC logic
REG_START_CYCLE = 12
REG_RESULT_CODE = 20 # Register where the vision app writes its result

class PLCSimulator:
    def __init__(self, host='127.0.0.1', port=5502):
        self.logger = logger
        self.host = host
        self.port = port
        
        # Initialize datastore
        self.datablock = ModbusSequentialDataBlock(0, [0] * 200)
        self.store = ModbusSlaveContext(hr=self.datablock)
        self.context = ModbusServerContext(slaves=self.store, single=True)
        
        # Set some initial values
        self.datablock.setValues(REG_CAM_ID, [1])
        self.datablock.setValues(REG_CYCLE_END, [0])
        self.datablock.setValues(REG_START_CYCLE, [0])
        self.datablock.setValues(REG_RESULT_CODE, [0])

        # Setup device identity
        self.identity = ModbusDeviceIdentification()
        self.identity.VendorName = 'Hutchinson'
        self.identity.ProductCode = 'PLC-SIM'
        self.identity.ProductName = 'PLC Simulator'
        self.identity.ModelName = 'Modbus TCP Simulator'
        self.identity.MajorMinorRevision = '1.0'

    def set_reference(self, ref_name):
        ref_name = ref_name.ljust(REF_NAME_LENGTH * 2, '\x00')
        registers = []
        for i in range(0, REF_NAME_LENGTH * 2, 2):
            word = (ord(ref_name[i]) << 8) | ord(ref_name[i+1])
            registers.append(word)
        self.datablock.setValues(REG_REF_NAME_START, registers)
        self.logger.info(f"Set reference to '{ref_name.strip()}'")

    def get_reference(self):
        registers = self.datablock.getValues(REG_REF_NAME_START, count=REF_NAME_LENGTH)
        ref_name = ""
        for reg in registers:
            high = (reg >> 8) & 0xFF
            low = reg & 0xFF
            if high != 0: ref_name += chr(high)
            if low != 0: ref_name += chr(low)
        return ref_name.strip('\x00')

    def run_server(self):
        self.logger.info(f"Starting Modbus TCP server on {self.host}:{self.port}")
        try:
            # StartTcpServer is a blocking call that runs its own asyncio loop.
            # This method is already running in a dedicated thread.
            StartTcpServer(context=self.context, identity=self.identity, address=(self.host, self.port))
        except Exception as e:
            self.logger.error(f"Server error: {e}", exc_info=True)

class PLCHmi(tb.Window):
    def __init__(self, plc_simulator):
        super().__init__(themename="darkly")
        self.plc = plc_simulator
        self.title("PLC Simulator HMI")
        
        # Center the window
        win_width, win_height = 600, 600
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width // 2) - (win_width // 2)
        y = (screen_height // 2) - (win_height // 2)
        self.geometry(f"{win_width}x{win_height}+{x}+{y}")
        self.resizable(True, True)

        container = ttk.Frame(self, padding=15)
        container.pack(expand=True, fill='both')

        # --- Recipe Control ---
        recipe_frame = ttk.LabelFrame(container, text="Recipe Control", padding=15)
        recipe_frame.pack(fill='x', pady=10)
        
        ttk.Label(recipe_frame, text="Select recipe to trigger CYCLE START:", font=("Helvetica", 10, "bold")).pack(pady=(0, 10))
        
        btn_container = ttk.Frame(recipe_frame)
        btn_container.pack(fill='x')
        
        # Grid buttons for responsiveness
        btn_container.columnconfigure(0, weight=1)
        ttk.Button(btn_container, text="Cam 1, Ref hhh", bootstyle="outline-primary", 
                   command=lambda: self.run_recipe(1, 'hhh')).grid(row=0, column=0, sticky="ew", pady=3)
        ttk.Button(btn_container, text="Cam 1, Ref 'REF02'", bootstyle="outline-primary", 
                   command=lambda: self.run_recipe(1, 'REF02')).grid(row=1, column=0, sticky="ew", pady=3)
        ttk.Button(btn_container, text="Cam 2, Ref 'XYZ'", bootstyle="outline-primary", 
                   command=lambda: self.run_recipe(2, 'XYZ')).grid(row=2, column=0, sticky="ew", pady=3)

        # --- Live Status ---
        status_frame = ttk.LabelFrame(container, text="Live Register Status", padding=15)
        status_frame.pack(fill='both', expand=True, pady=10)

        # Configure status_frame grid
        status_frame.columnconfigure(1, weight=1)

        self.vars = {
            "Cam ID": tk.StringVar(), "Reference": tk.StringVar(),
            "Start Cycle": tk.StringVar(), "Result Code": tk.StringVar()
        }
        
        def create_status_row(parent, label_text, var_name, row):
            ttk.Label(parent, text=label_text, font=("Helvetica", 10)).grid(row=row, column=0, sticky='w', padx=5, pady=8)
            lbl = ttk.Label(parent, textvariable=self.vars[var_name], font=("Helvetica", 11, "bold"))
            lbl.grid(row=row, column=1, sticky='w', padx=5, pady=8)
            return lbl

        create_status_row(status_frame, "Cam ID (Reg 10):", "Cam ID", 0)
        create_status_row(status_frame, "Reference (Reg 0-9):", "Reference", 1)
        create_status_row(status_frame, "Start Cycle (Reg 12):", "Start Cycle", 2)
        self.result_label = create_status_row(status_frame, "Result Code (Reg 20):", "Result Code", 3)

        self.update_ui()

    def run_recipe(self, cam_id, ref_name):
        self.plc.logger.info(f"--- HMI: Running Recipe: Cam {cam_id}, Ref '{ref_name}' ---")
        self.plc.set_reference(ref_name)
        self.plc.datablock.setValues(REG_CAM_ID, [cam_id])
        self.plc.datablock.setValues(REG_START_CYCLE, [1])

    def update_ui(self):
        # Read values from the datablock
        cam_id = self.plc.datablock.getValues(REG_CAM_ID, 1)[0]
        start_cycle = self.plc.datablock.getValues(REG_START_CYCLE, 1)[0]
        result_code = self.plc.datablock.getValues(REG_RESULT_CODE, 1)[0]
        ref_name = self.plc.get_reference()
        
        # Update UI variables
        self.vars["Cam ID"].set(str(cam_id))
        self.vars["Reference"].set(ref_name)
        self.vars["Start Cycle"].set('ON' if start_cycle else 'Off')
        
        result_text = {0: "IDLE", 1: "OK", 2: "NOK", 3: "BUSY"}.get(result_code, "UNKNOWN")
        self.vars["Result Code"].set(f"{result_text} ({result_code})")
        
        # Color-code the result
        if result_code == 1: self.result_label.config(bootstyle="success")
        elif result_code == 2: self.result_label.config(bootstyle="danger")
        else: self.result_label.config(bootstyle="default")

        self.after(250, self.update_ui)

def main():
    simulator = PLCSimulator()
    server_thread = threading.Thread(target=simulator.run_server, daemon=True)
    server_thread.start()
    time.sleep(1) # Give server time to start

    app = PLCHmi(simulator)
    app.mainloop()

if __name__ == "__main__":
    main()
