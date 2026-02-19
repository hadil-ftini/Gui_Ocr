import tkinter as tk
from tkinter import ttk, messagebox
import ttkbootstrap as tb
import logging
import threading
import time
import os
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
from pymodbus.device import ModbusDeviceIdentification

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("plc_simulator.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('PLCSimulator')

class PLCSimulator:
    def __init__(self, host='127.0.0.1', port=5502):
        self.logger = logger
        self.host = host
        self.port = port
        self.servo_position = 90.0
        self.aligned_status = 0
        self.servo_lock = threading.Lock()
        self.store = ModbusSlaveContext(
            hr=ModbusSequentialDataBlock(0, [0] * 200)
        )
        self.context = ModbusServerContext(slaves=self.store, single=True)
        self.store.setValues(3, 10, [1])
        self.store.setValues(3, 11, [0])
        self.store.setValues(3, 12, [0])
        self.identity = ModbusDeviceIdentification()
        self.identity.VendorName = 'Hutchinson'
        self.identity.ProductCode = 'PLC-SIM'
        self.identity.VendorUrl = ''
        self.identity.ProductName = 'PLC Simulator'
        self.identity.ModelName = 'Modbus TCP Simulator'
        self.identity.MajorMinorRevision = '1.0'

    def set_reference(self, ref_name):
        if len(ref_name) > 20:
            ref_name = ref_name[:20]
            self.logger.warning("Reference name truncated")
        ref_name = ref_name.ljust(20, '\x00')
        registers = []
        for i in range(0, 20, 2):
            high = ord(ref_name[i])
            low = ord(ref_name[i+1])
            registers.append((high << 8) | low)
        self.store.setValues(3, 0, registers)
        self.logger.info(f"Set reference to '{ref_name.strip()}'")

    def get_reference(self):
        registers = self.store.getValues(3, 0, count=10)
        ref_name = ""
        for reg in registers:
            high = (reg >> 8) & 0xFF
            low = reg & 0xFF
            if high != 0:
                ref_name += chr(high)
            if low != 0:
                ref_name += chr(low)
        return ref_name.strip('\x00')

    def run_server(self):
        self.logger.info(f"Starting Modbus TCP server on {self.host}:{self.port}")
        try:
            StartTcpServer(context=self.context, identity=self.identity, address=(self.host, self.port))
        except Exception as e:
            self.logger.error(f"Server error: {e}", exc_info=True)

    def _servo_simulation_loop(self):
        while True:
            try:
                direction_reg = self.store.getValues(3, 13, count=1)[0]
                pixel_offset = self.store.getValues(3, 14, count=1)[0]
                stop_signal = self.store.getValues(3, 15, count=1)[0]
                self.aligned_status = stop_signal
                direction = direction_reg - 65536 if direction_reg > 32767 else direction_reg
                if not stop_signal and direction != 0:
                    speed_factor = 0.05
                    movement = direction * speed_factor * (1 + pixel_offset / 100.0)
                    with self.servo_lock:
                        new_pos = self.servo_position + movement
                        self.servo_position = max(0, min(180, new_pos))
            except Exception as e:
                self.logger.error(f"Error in servo simulation: {e}", exc_info=True)
            time.sleep(0.02)

class PLCHmi(tb.Window):
    def __init__(self, plc_simulator):
        super().__init__(themename="darkly")
        self.plc = plc_simulator
        self.title("PLC Simulator HMI")
        self.geometry("600x450")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(expand=True, fill='both', padx=10, pady=10)

        self.create_control_tab()
        self.create_servo_tab()

        self.update_ui()

    def create_control_tab(self):
        control_frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(control_frame, text="PLC Control")

        # --- Recipe Control Frame ---
        recipe_frame = ttk.LabelFrame(control_frame, text="Recipe Control", padding=10)
        recipe_frame.pack(fill='x', expand=True, pady=5)
        
        ttk.Label(recipe_frame, text="Click a recipe to set parameters and send CYCLE START signal.").pack(pady=5)

        # Add some example recipe buttons
        ttk.Button(recipe_frame, text="Run Recipe: Cam 1, Ref '4'", command=lambda: self.run_recipe(cam_id=1, ref_name='4')).pack(fill='x', pady=3)
        ttk.Button(recipe_frame, text="Run Recipe: Cam 1, Ref '5'", command=lambda: self.run_recipe(cam_id=1, ref_name='5')).pack(fill='x', pady=3)
        ttk.Button(recipe_frame, text="Run Recipe: Cam 2, Ref 'MyRef'", command=lambda: self.run_recipe(cam_id=2, ref_name='MyRef')).pack(fill='x', pady=3)
        ttk.Button(recipe_frame, text="Run Recipe: Cam 2, Ref '1'", command=lambda: self.run_recipe(cam_id=2, ref_name='1')).pack(fill='x', pady=3)
        ttk.Button(recipe_frame, text="Run Recipe: Cam 2, Ref '2'", command=lambda: self.run_recipe(cam_id=2, ref_name='2')).pack(fill='x', pady=3)
        
        # Manual cycle end button
        ttk.Button(recipe_frame, text="MANUAL CYCLE END", command=self.send_cycle_end, bootstyle="danger").pack(fill='x', pady=10)


        # --- Live Status Frame ---
        status_frame = ttk.LabelFrame(control_frame, text="Live PLC->HMI Status", padding=10)
        status_frame.pack(fill='x', expand=True, pady=5)

        self.cam_id_var = tk.StringVar()
        self.ref_name_var = tk.StringVar()
        self.cycle_start_var = tk.StringVar()
        self.cycle_end_var = tk.StringVar()

        ttk.Label(status_frame, text="Cam ID:").grid(row=0, column=0, sticky='w', padx=5, pady=5)
        ttk.Label(status_frame, textvariable=self.cam_id_var).grid(row=0, column=1, sticky='w', padx=5, pady=5)

        ttk.Label(status_frame, text="Reference:").grid(row=1, column=0, sticky='w', padx=5, pady=5)
        ttk.Label(status_frame, textvariable=self.ref_name_var).grid(row=1, column=1, sticky='w', padx=5, pady=5)
        
        ttk.Label(status_frame, text="Cycle Start Flag:").grid(row=2, column=0, sticky='w', padx=5, pady=5)
        ttk.Label(status_frame, textvariable=self.cycle_start_var).grid(row=2, column=1, sticky='w', padx=5, pady=5)

        ttk.Label(status_frame, text="Cycle End Flag:").grid(row=3, column=0, sticky='w', padx=5, pady=5)
        ttk.Label(status_frame, textvariable=self.cycle_end_var).grid(row=3, column=1, sticky='w', padx=5, pady=5)

    def create_servo_tab(self):
        servo_frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(servo_frame, text="Servo Simulation")

        # --- HMI to PLC ---
        hmi_to_plc_frame = ttk.LabelFrame(servo_frame, text="HMI -> PLC (Received)", padding=10)
        hmi_to_plc_frame.pack(fill='x', expand=True, pady=5)

        self.direction_var = tk.StringVar()
        self.pixel_offset_var = tk.StringVar()
        self.aligned_status_var = tk.StringVar()
        self.servo_pos_var = tk.StringVar()

        ttk.Label(hmi_to_plc_frame, text="Direction:").pack(pady=2)
        ttk.Label(hmi_to_plc_frame, textvariable=self.direction_var, font=("Arial", 12, "bold")).pack(pady=2)

        ttk.Label(hmi_to_plc_frame, text="Pixel Offset:").pack(pady=2)
        ttk.Label(hmi_to_plc_frame, textvariable=self.pixel_offset_var, font=("Arial", 12, "bold")).pack(pady=2)

        self.aligned_status_label = ttk.Label(hmi_to_plc_frame, text="Aligned Status:", font=("Arial", 12, "bold"))
        self.aligned_status_label.pack(pady=2)
        self.aligned_status_value_label = ttk.Label(hmi_to_plc_frame, textvariable=self.aligned_status_var, font=("Arial", 12, "bold"))
        self.aligned_status_value_label.pack(pady=2)

        # --- Internal State ---
        internal_state_frame = ttk.LabelFrame(servo_frame, text="Internal State", padding=10)
        internal_state_frame.pack(fill='x', expand=True, pady=5)

        ttk.Label(internal_state_frame, text="Simulated Servo Position:").pack(pady=2)
        ttk.Label(internal_state_frame, textvariable=self.servo_pos_var, font=("Arial", 14, "bold")).pack(pady=2)

    def run_recipe(self, cam_id, ref_name):
        """Simulates the PLC setting recipe data and starting the cycle."""
        self.plc.logger.info(f"--- Running Recipe: Cam {cam_id}, Ref '{ref_name}' ---")
        
        # 1. Set reference name and camera ID
        self.plc.set_reference(ref_name)
        self.plc.store.setValues(3, 10, [cam_id])
        
        # 2. Reset cycle end flag
        self.plc.store.setValues(3, 11, [0])
        
        # 3. Set cycle start flag to trigger the vision app
        self.plc.store.setValues(3, 12, [1])
        
        # In a real PLC, the vision app would see the start flag,
        # do its work, and the PLC logic would eventually reset the flag.
        # For simulation, we'll reset it after a short delay.
        self.after(500, lambda: self.plc.store.setValues(3, 12, [0]))

    def send_cycle_end(self):
        """Simulates the PLC ending the cycle."""
        self.plc.logger.info("--- Sending Manual CYCLE END ---")
        self.plc.store.setValues(3, 11, [1])
        self.after(500, lambda: self.plc.store.setValues(3, 11, [0]))

    def update_ui(self):
        # Update PLC to HMI status
        self.cam_id_var.set(str(self.plc.store.getValues(3, 10, count=1)[0]))
        self.ref_name_var.set(self.plc.get_reference())
        self.cycle_start_var.set('On' if self.plc.store.getValues(3, 12, count=1)[0] else 'Off')
        self.cycle_end_var.set('On' if self.plc.store.getValues(3, 11, count=1)[0] else 'Off')

        # Update HMI to PLC
        direction_reg = self.plc.store.getValues(3, 13, count=1)[0]
        direction = direction_reg - 65536 if direction_reg > 32767 else direction_reg
        self.direction_var.set(str(direction))
        self.pixel_offset_var.set(str(self.plc.store.getValues(3, 14, count=1)[0]))
        aligned = self.plc.aligned_status
        self.aligned_status_var.set(str(aligned))

        if aligned:
            self.aligned_status_value_label.config(foreground="green")
        else:
            self.aligned_status_value_label.config(foreground="red")

        # Update Internal State
        with self.plc.servo_lock:
            self.servo_pos_var.set(f"{self.plc.servo_position:.2f}°")

        self.after(100, self.update_ui)

def main():
    simulator = PLCSimulator()
    server_thread = threading.Thread(target=simulator.run_server, daemon=True)
    server_thread.start()
    servo_thread = threading.Thread(target=simulator._servo_simulation_loop, daemon=True)
    servo_thread.start()

    app = PLCHmi(simulator)
    app.mainloop()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Simulator terminated by user")
    except Exception as e:
        logger.error(f"Simulator failed: {e}", exc_info=True)