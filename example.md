import logging
import time
import queue
import struct

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException
from pymodbus.payload import BinaryPayloadBuilder
from pymodbus.constants import Endian

class ModbusManager:
    def __init__(self, host="127.0.0.1", port=502, timeout=30):
        # Configure logging to both console and file
        self.logger = logging.getLogger('ModbusManager')
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            handlers=[
                logging.FileHandler("modbus_client.log"),
                logging.StreamHandler()
            ]
        )
        self.host = host
        self.port = port
        self.timeout = timeout
        self.client = None
        self.connected = False
        self.write_queue = queue.Queue()
        
        self.logger.info(f"ModbusManager initialized for {host}:{port}")

    def connect(self):
        """Connect to the Modbus server."""
        try:
            if self.client:
                self.client.close()
            self.client = ModbusTcpClient(self.host, port=self.port, timeout=self.timeout)
            self.connected = self.client.connect()
            if self.connected:
                self.logger.info(f"Connected to Modbus server at {self.host}:{self.port}")
            else:
                self.logger.error(f"Failed to connect to Modbus server at {self.host}:{self.port}")
            return self.connected
        except Exception as e:
            self.logger.error(f"Modbus connection error: {e}", exc_info=True)
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from the Modbus server."""
        try:
            if self.client:
                self.client.close()
                self.connected = False
                self.logger.info("Disconnected from Modbus server")
        except Exception as e:
            self.logger.error(f"Modbus disconnection error: {e}", exc_info=True)

    def read_start_cycle(self):
        """Read the start cycle signal from holding register 11."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not self.connected:
                    if not self.connect():
                        self.logger.error("Cannot connect to server")
                        return None
                # Read a single bit from register 11
                result = self.client.read_holding_registers(address=11, count=1)
                if result.isError():
                    self.logger.error(f"Modbus read error (start cycle): {result}")
                    self.connected = False
                    if attempt < max_retries - 1:
                        self.logger.info(f"Retrying read ({attempt + 1}/{max_retries})...")
                        time.sleep(1)
                    continue
                
                # The signal is a boolean value (0 or 1)
                start_cycle = result.registers[0] == 1
                self.logger.debug(f"Read start cycle signal from register 11: {start_cycle}")
                return start_cycle
            except ModbusException as e:
                self.logger.error(f"Modbus read exception (start cycle): {e}", exc_info=True)
                self.connected = False
                if attempt < max_retries - 1:
                    self.logger.info(f"Retrying read ({attempt + 1}/{max_retries})...")
                    time.sleep(1)
                continue
            except Exception as e:
                self.logger.error(f"Modbus read error (start cycle): {e}", exc_info=True)
                self.connected = False
                return None
        self.logger.error("Max retries reached for read_start_cycle")
        return None

    def read_plc_input_block(self):
        """Reads a contiguous block of input data from the PLC, including cam_id, start_cycle, and end_cycle."""
        max_retries = 3
        # Starting address is 10 (for cam_id), and we read 3 consecutive registers.
        start_address = 10
        register_count = 3

        for attempt in range(max_retries):
            try:
                if not self.connected:
                    if not self.connect():
                        self.logger.error("Cannot connect to server for block read")
                        return None
                
                # Perform a single read of 3 registers starting from address 10
                result = self.client.read_holding_registers(address=start_address, count=register_count)
                if result.isError():
                    self.logger.error(f"Modbus block read error: {result}")
                    self.connected = False
                    if attempt < max_retries - 1:
                        self.logger.info(f"Retrying block read ({attempt + 1}/{max_retries})...")
                        time.sleep(1)
                    continue
                
                # The result.registers will be a list: [value_at_10, value_at_11, value_at_12]
                cam_id = result.registers[0]
                start_cycle = result.registers[1] == 1
                end_cycle = result.registers[2] == 1
                
                self.logger.debug(f"Block read successful: cam_id={cam_id}, start_cycle={start_cycle}, end_cycle={end_cycle}")
                return {
                    "cam_id": cam_id,
                    "start_cycle": start_cycle,
                    "end_cycle": end_cycle
                }

            except ModbusException as e:
                self.logger.error(f"Modbus block read exception: {e}", exc_info=True)
                self.connected = False
                if attempt < max_retries - 1:
                    self.logger.info(f"Retrying block read ({attempt + 1}/{max_retries})...")
                    time.sleep(1)
                continue
            except Exception as e:
                self.logger.error(f"General block read error: {e}", exc_info=True)
                self.connected = False
                return None
        self.logger.error("Max retries reached for read_plc_input_block")
        return None

    def read_reference_and_camera_id(self):
        """Read reference name (registers 0-9) and camera ID (register 20)."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not self.connected:
                    if not self.connect():
                        self.logger.error("Cannot connect to server")
                        return None
                
                # Read reference name (10 registers from address 0)
                ref_name_result = self.client.read_holding_registers(address=0, count=10)
                if ref_name_result.isError():
                    self.logger.error(f"Modbus read error (ref_name): {ref_name_result}")
                    self.connected = False
                    if attempt < max_retries - 1:
                        self.logger.info(f"Retrying read ({attempt + 1}/{max_retries})...")
                        time.sleep(1)
                    continue
                
                ref_name = ""
                for i in range(10):
                    high = (ref_name_result.registers[i] >> 8) & 0xFF
                    low = ref_name_result.registers[i] & 0xFF
                    ref_name += chr(high) + chr(low)
                ref_name = ref_name.strip('\x00').strip()

                # Read camera ID (1 register from address 10)
                cam_id_result = self.client.read_holding_registers(10)
                if cam_id_result.isError():
                    self.logger.error(f"Modbus read error (cam_id): {cam_id_result}")
                    self.connected = False
                    if attempt < max_retries - 1:
                        self.logger.info(f"Retrying read ({attempt + 1}/{max_retries})...")
                        time.sleep(1)
                    continue
                
                cam_id = cam_id_result.registers[0]
                
                self.logger.debug(f"Read reference and camera ID: ref_name={ref_name}, cam_id={cam_id}")
                return {
                    "reference": ref_name,
                    "cam_id": cam_id
                }
            except ModbusException as e:
                self.logger.error(f"Modbus read exception (ref/cam_id): {e}", exc_info=True)
                self.connected = False
                if attempt < max_retries - 1:
                    self.logger.info(f"Retrying read ({attempt + 1}/{max_retries})...")
                    time.sleep(1)
                continue
            except Exception as e:
                self.logger.error(f"Modbus read error (ref/cam_id): {e}", exc_info=True)
                self.connected = False
                return None
        self.logger.error("Max retries reached for read_reference_and_camera_id")
        return None

    

    def _execute_write_outputs(self, direction, pixel_offset):
        """Internal method to execute Modbus write operations."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not self.connected:
                    if not self.connect():
                        self.logger.error("Failed to connect to PLC")
                        return False

                # Set slave ID
                self.client.unit_id = 1
                
                # Clamp and convert direction to a signed 16-bit integer
                direction_int = int(max(-1, min(1, direction))) # Clamp to -1, 0, 1

                # Write pixel_offset value to register 13
                result_offset = self.client.write_register(13, int(pixel_offset))
                if result_offset.isError():
                    self.logger.error(f"Failed to write pixel offset {pixel_offset} to register 13: {result_offset}")
                    self.connected = False
                    if attempt < max_retries - 1:
                        self.logger.info(f"Retrying write ({attempt + 1}/{max_retries})...")
                        time.sleep(1)
                        continue
                    return False
                else:
                    self.logger.debug(f"Successfully wrote pixel offset {pixel_offset} to register 13")

                # Write direction value to register 14
                result_direction = self.client.write_register(14, direction_int, signed=True)
                if result_direction.isError():
                    self.logger.error(f"Failed to write direction {direction_int} to register 14: {result_direction}")
                    self.connected = False
                    if attempt < max_retries - 1:
                        self.logger.info(f"Retrying write ({attempt + 1}/{max_retries})...")
                        time.sleep(1)
                        continue
                    return False
                else:
                    self.logger.debug(f"Successfully wrote direction {direction_int} to register 14")
                
                return True

            except ModbusException as e:
                self.logger.error(f"Modbus write exception: {e}", exc_info=True)
                self.connected = False
                if attempt < max_retries - 1:
                    self.logger.info(f"Retrying write ({attempt + 1}/{max_retries})...")
                    time.sleep(1)
                    continue
            except Exception as e:
                self.logger.error(f"Modbus write error: {e}", exc_info=True)
                return False
        self.logger.error("Max retries reached for _execute_write_outputs")
        return False

    def queue_write_outputs(self, direction, pixel_offset):
        """Queue Modbus write operations for asynchronous execution."""
        try:
            self.write_queue.put((direction, pixel_offset), timeout=0.1)
            self.logger.debug(f"Queued Modbus write: direction={direction}, pixel_offset={pixel_offset}")
            return True
        except queue.Full:
            self.logger.warning("Modbus write queue is full, dropping command.")
            return False
        except Exception as e:
            self.logger.error(f"Error queuing Modbus write: {e}", exc_info=True)
            return False

    def cleanup(self):
        """Clean up resources."""
        self.disconnect()

def main():
    """Example usage of ModbusManager."""
    modbus = ModbusManager(host="192.168.0.50", port=502)
    try:
        # Example: Write outputs
        direction = 1
        pixel_offset = 10
        modbus.queue_write_outputs(direction, pixel_offset)
        # In a real application, you would have a separate thread consuming from the queue
        # For this example, we'll just execute it directly for demonstration
        modbus._execute_write_outputs(direction, pixel_offset)
        
    except KeyboardInterrupt:
        modbus.logger.info("Client terminated by user")
    finally:
        modbus.cleanup()

if __name__ == "__main__":
    main()