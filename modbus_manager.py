import logging
import time
import queue
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

# --------------------
# CONFIGURATION
# --------------------
# Register map based on user example and application needs
REG_REF_NAME_START = 0
REF_NAME_LENGTH = 10     # 10 registers for the name
REG_CAM_ID = 10
REG_START_CYCLE = 12
REG_END_CYCLE = 12

REG_RESULT_CODE = 20     # Register to write OK/NOK status to
REG_PIXEL_OFFSET = 21    # Example output register
REG_DIRECTION = 22       # Example output register

# Result Codes
RESULT_IDLE = 0
RESULT_OK = 1
RESULT_NOK = 2
RESULT_BUSY = 3

class ModbusManager:
    """
    A Modbus Client to actively poll and communicate with a PLC.
    This class is based on the user-provided example.md.
    """
    def __init__(self, host='127.0.0.1', port=5502, timeout=30):
        self.logger = logging.getLogger('ModbusManager')
        if not self.logger.handlers:
            logging.basicConfig(
                level=logging.INFO,
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
        
        self.logger.info(f"ModbusManager initialized for {host}:{port}")

    def connect(self):
        """Connect to the Modbus server."""
        if self.connected:
            return True
        try:
            self.client = ModbusTcpClient(self.host, port=self.port, timeout=self.timeout)
            self.connected = self.client.connect()
            if self.connected:
                self.logger.info(f"Connected to Modbus PLC at {self.host}:{self.port}")
            else:
                self.logger.error(f"Failed to connect to Modbus PLC.")
            return self.connected
        except Exception as e:
            self.logger.error(f"Modbus connection error: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from the Modbus server."""
        if self.client:
            self.client.close()
        self.connected = False
        self.logger.info("Disconnected from Modbus PLC")

    def _read_registers(self, address, count):
        """Generic, retrying register read function."""
        if not self.connect():
            return None
        try:
            result = self.client.read_holding_registers(address=address, count=count)
            if result.isError():
                self.logger.error(f"Modbus read error at {address}: {result}")
                self.connected = False
                return None
            return result.registers
        except ModbusException as e:
            self.logger.error(f"Modbus read exception at {address}: {e}")
            self.connected = False
            return None

    def read_plc_inputs(self):
        """
        Reads a block of input data from the PLC to get commands.
        Reads reference name, cam_id, and start_cycle signal.
        """
        # Read the whole block from the first ref name register to the start cycle register
        block_size = REG_START_CYCLE - REG_REF_NAME_START + 1
        registers = self._read_registers(REG_REF_NAME_START, block_size)

        if registers is None:
            return None

        try:
            # Decode Reference Name (from registers 0-9)
            ref_words = registers[0:REF_NAME_LENGTH]
            ref_bytes = b"".join([word.to_bytes(2, 'big') for word in ref_words])
            ref_name = ref_bytes.decode('ascii', errors='ignore').strip('\x00').strip()

            # Get Cam ID (from register 10)
            cam_id = registers[REG_CAM_ID - REG_REF_NAME_START]

            # Get Start Cycle (from register 11)
            start_cycle = registers[REG_START_CYCLE - REG_REF_NAME_START] == 1
            
            self.logger.debug(f"PLC Inputs Read: Ref='{ref_name}', CamID={cam_id}, Start={start_cycle}")
            return {
                "reference": ref_name,
                "cam_id": cam_id,
                "start_cycle": start_cycle
            }
        except (IndexError, UnicodeDecodeError) as e:
            self.logger.error(f"Error processing PLC input block: {e}")
            return None
            
    def _write_register(self, address, value):
        """Generic, retrying single register write function."""
        if not self.connect():
            return False
        try:
            result = self.client.write_register(address, value)
            if result.isError():
                self.logger.error(f"Modbus write error at {address}: {result}")
                self.connected = False
                return False
            return True
        except ModbusException as e:
            self.logger.error(f"Modbus write exception at {address}: {e}")
            self.connected = False
            return False

    def write_result(self, result_code):
        """Writes the test result code (OK/NOK/etc.) to the PLC."""
        self.logger.info(f"Writing result code {result_code} to register {REG_RESULT_CODE}")
        return self._write_register(REG_RESULT_CODE, result_code)

    def acknowledge_start(self):
        """Writes 0 back to the start_cycle register to signal completion."""
        self.logger.debug(f"Acknowledging cycle start by writing 0 to {REG_START_CYCLE}")
        return self._write_register(REG_START_CYCLE, 0)
