import cv2
from PIL import Image, ImageTk
import pytesseract
import numpy as np
from difflib import SequenceMatcher

# DISPLAY_WIDTH = 840 # REMOVED: Replaced by dynamic target dimensions
OCR_MATCH_THRESHOLD = 0.8  # 80% similarity required for a match

class CameraApp:
    def __init__(self):
        self.cap = None
        self.is_running = False
        self.display_scale = 1.0
        self.current_roi = None
        self.expected_text = ""
        self.temp_roi = None
        # Add state for results
        self.last_detected_text = ""
        self.is_match = False

    def start_camera(self, camera_index=1):
        self.cap = cv2.VideoCapture(1)
        self.is_running = self.cap.isOpened()
        return self.is_running

    def stop_camera(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.is_running = False

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
        if self.current_roi is None or not self.expected_text:
            self.is_match = False
            self.last_detected_text = ""
            return

        x, y, w, h = self.current_roi
        
        # Ensure ROI is within frame bounds
        h_frame, w_frame, _ = frame.shape
        if x + w > w_frame or y + h > h_frame:
            self.is_match = False
            self.last_detected_text = "ROI out of bounds"
            return

        # Crop and process image for OCR
        roi_frame = frame[y:y+h, x:x+w]
        gray = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2GRAY)
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

        # OCR
        try:
            detected_text = pytesseract.image_to_string(thresh, config='--psm 6').strip()
            self.last_detected_text = detected_text
        except Exception as e:
            self.last_detected_text = "OCR Error"
            self.is_match = False
            return

        # Compare
        if detected_text:
            ratio = SequenceMatcher(None, self.expected_text.lower(), detected_text.lower()).ratio()
            self.is_match = ratio >= OCR_MATCH_THRESHOLD
        else:
            self.is_match = False

    def get_frame(self, target_width=None, target_height=None): # ADD target_width, target_height parameters
        if not self.is_running or self.cap is None: return None, None
        ret, frame = self.cap.read()
        if not ret: return None, None
        
        # Run the core logic
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

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)

        # RESIZING LOGIC
        if target_width and target_height and target_width > 0 and target_height > 0:
            original_width, original_height = pil.size
            
            # Calculate ratios
            width_ratio = target_width / original_width
            height_ratio = target_height / original_height
            
            # Use the smaller ratio to fit within the target dimensions while maintaining aspect ratio
            scale_ratio = min(width_ratio, height_ratio)
            
            new_width = int(original_width * scale_ratio)
            new_height = int(original_height * scale_ratio)
            
            # Ensure at least 1 pixel dimension
            new_width = max(1, new_width)
            new_height = max(1, new_height)

            pil = pil.resize((new_width, new_height), Image.Resampling.LANCZOS)
            self.display_scale = scale_ratio # Store the actual scale used
        else:
            self.display_scale = 1.0 # If no target provided, no scaling happens
            
        return ImageTk.PhotoImage(pil), self.is_match