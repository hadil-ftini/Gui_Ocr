import cv2
from PIL import Image, ImageTk
import pytesseract
import numpy as np
import re

# DISPLAY_WIDTH = 840 # REMOVED: Replaced by dynamic target dimensions
OCR_MATCH_THRESHOLD = 0.8  # kept for compatibility but exact match is used by default

class CameraApp:
    def __init__(self):
        self.cap = None
        self.is_running = False
        self.display_scale = 1.0
        self.display_scale_x = 1.0
        self.display_scale_y = 1.0
        self.current_roi = None
        self.expected_text = ""
        self.temp_roi = None
        # Add state for results
        self.last_detected_text = ""
        self.is_match = False
        # Cache optimizations
        self._last_cached_dims = (None, None)
        self._last_pil_image = None
        self._last_frame_hash = 0
        # Test OCR
        self._run_test_ocr = False
        self.test_result = None

    def start_camera(self, camera_index=1):
        self.cap = cv2.VideoCapture(camera_index)
        # Lower capture resolution for Raspberry Pi performance while keeping sufficient detail
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.is_running = self.cap.isOpened()
        return self.is_running

    def stop_camera(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.is_running = False

    def _clamp_roi(self, x, y, w, h, frame_w, frame_h):
        """Ensures ROI is within frame boundaries."""
        nx = max(0, min(x, frame_w - 1))
        ny = max(0, min(y, frame_h - 1))
        nw = max(1, min(w, frame_w - nx))
        nh = max(1, min(h, frame_h - ny))
        return int(nx), int(ny), int(nw), int(nh)

    def set_roi(self, x, y, w, h):
        if w <= 0 or h <= 0: return False
        self.current_roi = (int(x), int(y), int(w), int(h))
        # Reset results when ROI changes
        self.last_detected_text = ""
        self.is_match = False
        return True

    def set_roi_temp(self, x, y, w, h):
        self.temp_roi = (x, y, w, h)

    def clear_roi(self):
        self.current_roi = None
        self.temp_roi = None
        self.expected_text = ""
        self.last_detected_text = ""
        self.is_match = False

    def _process_frame(self, frame):
        """Internal method to run OCR and comparison if ROI and expected_text are set."""
        if not self.expected_text or self.current_roi is None:
            self.is_match = False
            self.last_detected_text = ""
            return

        h_frame, w_frame, _ = frame.shape
        x, y, w, h = self._clamp_roi(*self.current_roi, w_frame, h_frame)

        # Crop and process image for OCR
        try:
            roi_frame = frame[y:y+h, x:x+w]
            if roi_frame.size == 0:
                raise ValueError("Empty ROI")
            gray = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2GRAY)
            thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        except Exception:
            self.is_match = False
            self.last_detected_text = "ROI Error"
            return

        # OCR with whitelist
        try:
            config = '--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-.'
            detected_text = pytesseract.image_to_string(thresh, config=config)
            filtered_text = re.sub(r'[^A-Za-z0-9\-.]+', '', detected_text).strip()
            self.last_detected_text = filtered_text
        except Exception:
            self.last_detected_text = "OCR Error"
            self.is_match = False
            return

        # Compare detected text with the selected reference text
        if filtered_text:
            self.is_match = filtered_text.lower() == self.expected_text.strip().lower()
        else:
            self.is_match = False

        if self._run_test_ocr:
            self.test_result = (filtered_text, self.is_match)
            # Do not reset _run_test_ocr here, let the UI control it

    def get_frame(self, target_width=None, target_height=None, run_ocr=False): 
        if not self.is_running or self.cap is None: return None, None
        ret, frame = self.cap.read()
        if not ret: return None, None
        
        # Run the core logic
        if run_ocr:
            self._process_frame(frame)

        # --- DRAWING LOGIC ---
        roi_color = (0, 255, 0) if self.is_match else (0, 0, 255)
        if self.current_roi:
            x, y, w, h = self.current_roi
            cv2.rectangle(frame, (x, y), (x + w, y + h), roi_color, 3)
            # Put detected text on frame
            cv2.putText(frame, self.last_detected_text, (x, y - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, roi_color, 2)

        if self.temp_roi:
            tx, ty, tw, th = self.temp_roi
            cv2.rectangle(frame, (tx, ty), (tx + tw, ty + th), (255, 120, 0), 2)

        # RESIZING LOGIC with dimension caching
        if target_width and target_height and target_width > 0 and target_height > 0:
            target_dims = (int(target_width), int(target_height))
            original_width = frame.shape[1]
            original_height = frame.shape[0]
            frame = cv2.resize(frame, target_dims, interpolation=cv2.INTER_LINEAR)
            self._last_cached_dims = target_dims
            self.display_scale_x = target_dims[0] / original_width
            self.display_scale_y = target_dims[1] / original_height
            self.display_scale = self.display_scale_x
        else:
            self.display_scale_x = 1.0
            self.display_scale_y = 1.0
            self.display_scale = 1.0
            self._last_cached_dims = (None, None)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        return ImageTk.PhotoImage(pil), self.is_match