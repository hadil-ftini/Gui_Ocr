# ==================== modbus_manager.py ====================
import logging
import time
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException, ConnectionException

# Updated Register Map (as requested)
REG_REF_NAME_START = 0
REF_NAME_LENGTH = 15
REG_START_TEST = 15
REG_TEST_RESULT = 16
REG_MODBUS_ENABLE = 17

# Result Codes used by the system
RESULT_OK = 1
RESULT_NOK = 0
RESULT_IDLE = 2

class ModbusManager:
    def __init__(self, host='198.168.0.3', port=502, timeout=5):
        self.logger = logging.getLogger('ModbusManager')
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                            handlers=[logging.FileHandler("modbus_client.log"), logging.StreamHandler()])
        
        self.host = host
        self.port = port
        self.timeout = timeout
        self.client = None
        self.connected = False

    def connect(self):
        if self.connected and self.client:
            return True
        try:
            self.client = ModbusTcpClient(self.host, port=self.port, timeout=self.timeout)
            self.connected = self.client.connect()
            if self.connected:
                self.logger.info(f"Connected to Modbus PLC at {self.host}:{self.port}")
            return self.connected
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            self.connected = False
            return False

    def disconnect(self):
        if self.client:
            try:
                self.client.close()
            except:
                pass
        self.connected = False
        self.logger.info("Disconnected from PLC")

    def _read_registers(self, address, count):
        if not self.connect():
            return None
        try:
            result = self.client.read_holding_registers(address, count)
            if result.isError():
                self.logger.error(f"Read error at reg {address}: {result}")
                self.connected = False
                return None
            return result.registers
        except (ModbusException, ConnectionException) as e:
            self.logger.error(f"Read exception at reg {address}: {e}")
            self.connected = False
            return None

    def read_plc_inputs(self):
        registers = self._read_registers(REG_REF_NAME_START, REF_NAME_LENGTH + 1)
        if registers is None or len(registers) < REF_NAME_LENGTH + 1:
            return None

        try:
            ref_words = registers[:REF_NAME_LENGTH]
            ref_name = self._decode_reference(ref_words)

            start_test = registers[REF_NAME_LENGTH] == 1

            self.logger.debug(f"PLC → Ref='{ref_name}', StartTest={start_test}")
            return {"reference": ref_name, "start_test": start_test}
        except Exception as e:
            self.logger.error(f"Error decoding PLC data: {e}")
            return None

    def _decode_reference(self, ref_words):
        """
        Decode reference string from holding registers.
        Supports both common PLC formats:
        1) 2 chars per register (high byte + low byte)
        2) 1 char per register (low byte only, high byte is 0)
        """
        def is_printable_ascii(v):
            return 32 <= v <= 126

        # Strategy A: 2 chars/register (high then low)
        packed_chars = []
        for word in ref_words:
            hi = (word >> 8) & 0xFF
            lo = word & 0xFF
            if hi == 0 and lo == 0 and packed_chars:
                break
            if is_printable_ascii(hi):
                packed_chars.append(chr(hi))
            if is_printable_ascii(lo):
                packed_chars.append(chr(lo))
        packed = ''.join(packed_chars).strip()

        # Strategy B: low byte only per register
        low_chars = []
        for word in ref_words:
            lo = word & 0xFF
            if lo == 0 and low_chars:
                break
            if is_printable_ascii(lo):
                low_chars.append(chr(lo))
        low_only = ''.join(low_chars).strip()

        # Strategy C: high byte only per register
        high_chars = []
        for word in ref_words:
            hi = (word >> 8) & 0xFF
            if hi == 0 and high_chars:
                break
            if is_printable_ascii(hi):
                high_chars.append(chr(hi))
        high_only = ''.join(high_chars).strip()

        candidates = [packed, low_only, high_only]
        candidates = [c for c in candidates if c]
        if not candidates:
            return ""
        # Prefer the longest decoded value to avoid truncated one-char results.
        return max(candidates, key=len)

    def _write_register(self, address, value):
        if not self.connect():
            return False
        try:
            result = self.client.write_register(address, value)
            if result.isError():
                self.logger.error(f"Write error at {address}: {result}")
                self.connected = False
                return False
            return True
        except Exception as e:
            self.logger.error(f"Write exception at {address}: {e}")
            self.connected = False
            return False

    def write_result(self, result_code):
        self.logger.info(f"Writing result {result_code} → register {REG_TEST_RESULT}")
        return self._write_register(REG_TEST_RESULT, result_code)

    def acknowledge_start(self):
        self.logger.debug(f"Acknowledging start (write 0 to reg {REG_START_TEST})")
        return self._write_register(REG_START_TEST, 0)