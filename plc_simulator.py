import tkinter as tk
from tkinter import ttk
import ttkbootstrap as tb
import logging
import threading
import time
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusServerContext
from pymodbus.datastore.context import ModbusSlaveContext
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.device import ModbusDeviceIdentification

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                    handlers=[logging.FileHandler("plc_simulator.log"), logging.StreamHandler()])
logger = logging.getLogger('PLCSimulator')

# --- Updated Register Map ---
REG_REF_NAME_START = 0
REF_NAME_LENGTH = 15        # Registers 0-14 (30 bytes)
REG_START_TEST = 15
REG_TEST_RESULT = 16
REG_MODBUS_ENABLE = 17

class PLCSimulator:
    def __init__(self, host='127.0.0.1', port=5502):
        self.logger = logger
        self.host = host
        self.port = port
        
        # Initialize datastore with more space
        self.datablock = ModbusSequentialDataBlock(0, [0] * 100)
        # zero_mode=True keeps Modbus addresses 0-based, matching GUI client map.
        # Without this, reads/writes are shifted by one register (e.g. "test" -> "st").
        self.store = ModbusSlaveContext(hr=self.datablock, zero_mode=True)
        self.context = ModbusServerContext(slaves=self.store, single=True)
        
        # Initial values
        self.datablock.setValues(REG_START_TEST, [0])
        self.datablock.setValues(REG_TEST_RESULT, [0])
        self.datablock.setValues(REG_MODBUS_ENABLE, [1])

        # Device identity
        self.identity = ModbusDeviceIdentification()
        self.identity.VendorName = 'Hutchinson'
        self.identity.ProductCode = 'PLC-SIM'
        self.identity.ProductName = 'PLC Simulator'
        self.identity.ModelName = 'Modbus TCP Simulator'
        self.identity.MajorMinorRevision = '1.0'

    def set_reference(self, ref_name):
        # Pad to 30 characters (15 registers × 2 bytes)
        ref_name = ref_name.ljust(REF_NAME_LENGTH * 2, '\x00')
        registers = []
        for i in range(0, REF_NAME_LENGTH * 2, 2):
            word = (ord(ref_name[i]) << 8) | ord(ref_name[i + 1])
            registers.append(word)
        
        self.datablock.setValues(REG_REF_NAME_START, registers)
        self.logger.info(f"Set reference to '{ref_name.strip()}'")

    def get_reference(self):
        registers = self.datablock.getValues(REG_REF_NAME_START, count=REF_NAME_LENGTH)
        ref_name = ""
        for reg in registers:
            high = (reg >> 8) & 0xFF
            low = reg & 0xFF
            if high: ref_name += chr(high)
            if low: ref_name += chr(low)
        return ref_name.strip('\x00').strip()

    def run_server(self):
        self.logger.info(f"Starting Modbus TCP server on {self.host}:{self.port}")
        try:
            StartTcpServer(context=self.context, identity=self.identity, address=(self.host, self.port))
        except Exception as e:
            self.logger.error(f"Server error: {e}", exc_info=True)

class PLCHmi(tb.Window):
    def __init__(self, plc_simulator):
        super().__init__(themename="darkly")
        self.plc = plc_simulator
        self.title("PLC Simulator HMI")
        
        win_width, win_height = 620, 620
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width // 2) - (win_width // 2)
        y = (screen_height // 2) - (win_height // 2)
        self.geometry(f"{win_width}x{win_height}+{x}+{y}")
        self.resizable(True, True)

        container = ttk.Frame(self, padding=15)
        container.pack(expand=True, fill='both')

        # Recipe Control
        recipe_frame = ttk.LabelFrame(container, text="Recipe Control", padding=15)
        recipe_frame.pack(fill='x', pady=10)
        

        ttk.Label(recipe_frame, text="Select reference to send to GUI:", font=("Helvetica", 10, "bold")).pack(pady=(0, 10))
        
        btn_container = ttk.Frame(recipe_frame)
        btn_container.pack(fill='x')
        btn_container.columnconfigure(0, weight=1)

        ttk.Button(btn_container, text="Ref 'hadil'", bootstyle="outline-primary",
                   command=lambda: self.run_recipe('hadil')).grid(row=0, column=0, sticky="ew", pady=4)
        ttk.Button(btn_container, text="Ref 'test'", bootstyle="outline-primary",
                   command=lambda: self.run_recipe('test')).grid(row=1, column=0, sticky="ew", pady=4)
        ttk.Button(btn_container, text="Ref 'TIA'", bootstyle="outline-primary",
                   command=lambda: self.run_recipe('TIA')).grid(row=2, column=0, sticky="ew", pady=4)

        # Live Status
        status_frame = ttk.LabelFrame(container, text="Live Register Status", padding=15)
        status_frame.pack(fill='both', expand=True, pady=10)
        status_frame.columnconfigure(1, weight=1)

        self.vars = {
            "Reference": tk.StringVar(value=""),
            "Start Test": tk.StringVar(value="Off"),
            "Test Result": tk.StringVar(value="IDLE")
        }
        
        def create_row(parent, text, var_name, row):
            ttk.Label(parent, text=text, font=("Helvetica", 10)).grid(row=row, column=0, sticky='w', padx=5, pady=8)
            ttk.Label(parent, textvariable=self.vars[var_name], font=("Helvetica", 11, "bold")).grid(row=row, column=1, sticky='w', padx=5, pady=8)

        create_row(status_frame, "Reference (0-14):", "Reference", 0)
        create_row(status_frame, "Start Test (15):", "Start Test", 1)
        self.result_lbl = ttk.Label(status_frame, textvariable=self.vars["Test Result"], font=("Helvetica", 11, "bold"))
        self.result_lbl.grid(row=2, column=1, sticky='w', padx=5, pady=8)
        ttk.Label(status_frame, text="Test Result (16):", font=("Helvetica", 10)).grid(row=2, column=0, sticky='w', padx=5, pady=8)

        self.update_ui()

    def run_recipe(self, ref_name):
        self.plc.logger.info(f"--- HMI: Sending reference '{ref_name}' ---")
        self.plc.set_reference(ref_name)
        # Reference selection only; GUI test remains manual from operator side.
        self.plc.datablock.setValues(REG_START_TEST, [0])

    def update_ui(self):
        ref = self.plc.get_reference()
        start = self.plc.datablock.getValues(REG_START_TEST, 1)[0]
        result = self.plc.datablock.getValues(REG_TEST_RESULT, 1)[0]

        self.vars["Reference"].set(ref or "—")
        self.vars["Start Test"].set("ON" if start else "Off")

        if result == 1:
            self.vars["Test Result"].set("OK")
            self.result_lbl.config(foreground="green")
        elif result == 0:
            self.vars["Test Result"].set("NOK")
            self.result_lbl.config(foreground="red")
        else:
            self.vars["Test Result"].set(f"IDLE ({result})")
            self.result_lbl.config(foreground="gray")

        self.after(300, self.update_ui)

def main():
    simulator = PLCSimulator()
    server_thread = threading.Thread(target=simulator.run_server, daemon=True)
    server_thread.start()
    time.sleep(1.2)   # Give server more time to start

    app = PLCHmi(simulator)
    app.mainloop()

if __name__ == "__main__":
    main()