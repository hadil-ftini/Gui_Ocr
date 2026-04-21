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
        self.last_frame = None
        # Add state for results
        self.last_detected_text = ""
        self.is_match = False
        self.ocr_done = False
        # Cache optimizations
        self._last_cached_dims = (None, None)
        self._last_pil_image = None
        self._last_frame_hash = 0

    def start_camera(self, camera_index=1):
        camera_index=1
        self.cap = cv2.VideoCapture(1)
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
        self.ocr_done = False
        return True

    def set_roi_temp(self, x, y, w, h):
        self.temp_roi = (x, y, w, h)

    def clear_roi(self):
        self.current_roi = None
        self.temp_roi = None
        self.expected_text = ""
        self.last_detected_text = ""
        self.is_match = False
        self.ocr_done = False

    def _process_frame(self, frame):
        """Internal method to run OCR and comparison if ROI and expected_text are set."""
        if not self.expected_text or self.current_roi is None:
            self.is_match = False
            self.last_detected_text = ""
            self.ocr_done = False
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
            self.ocr_done = True
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
            self.ocr_done = True
            return

        # Compare detected text with the selected reference text
        if filtered_text:
            self.is_match = filtered_text.lower() == self.expected_text.strip().lower()
        else:
            self.is_match = False

        self.ocr_done = True

    def get_frame(self, target_width=None, target_height=None, run_ocr=False): 
        if not self.is_running or self.cap is None: return None, None
        ret, frame = self.cap.read()
        if not ret: return None, None
        self.last_frame = frame.copy()
        
        # Run the core logic only when requested by caller
        if run_ocr:
            self._process_frame(frame)

        # --- DRAWING LOGIC ---
        if self.current_roi:
            x, y, w, h = self.current_roi
            if self.ocr_done:
                roi_color = (0, 255, 0) if self.is_match else (0, 0, 255)
                top_label_text = "OK" if self.is_match else "NOK"
            else:
                roi_color = (255, 255, 0)
                top_label_text = ""
            cv2.rectangle(frame, (x, y), (x + w, y + h), roi_color, 3)
            if top_label_text:
                # Draw match state above the ROI when possible
                label_size, _ = cv2.getTextSize(top_label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
                label_w, label_h = label_size
                label_x = max(4, min(x, frame.shape[1] - label_w - 4))
                label_y = y - 10 if y - 20 > 0 else y + h + label_h + 15
                bg_tl = (label_x - 4, label_y - label_h - 4)
                bg_br = (label_x + label_w + 4, label_y + 4)
                cv2.rectangle(frame, bg_tl, bg_br, (0, 0, 0), cv2.FILLED)
                cv2.putText(frame, top_label_text, (label_x, label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, roi_color, 2, cv2.LINE_AA)

            if self.last_detected_text:
                # Draw the detected OCR text below the ROI box
                content_text = self.last_detected_text
                text_size, _ = cv2.getTextSize(content_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                text_w, text_h = text_size
                text_x = max(4, min(x, frame.shape[1] - text_w - 4))
                text_y = y + h + text_h + 20
                if text_y + 4 > frame.shape[0]:
                    text_y = y - 10
                bg_tl = (text_x - 4, text_y - text_h - 4)
                bg_br = (text_x + text_w + 4, text_y + 4)
                cv2.rectangle(frame, bg_tl, bg_br, (0, 0, 0), cv2.FILLED)
                cv2.putText(frame, content_text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

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

    def perform_ocr_once(self):
        if self.current_roi is None or not self.expected_text:
            self.last_detected_text = ""
            self.is_match = False
            self.ocr_done = False
            return "", False

        frame = None
        if self.last_frame is not None:
            frame = self.last_frame.copy()
        elif self.cap is not None:
            ret, frame = self.cap.read()
            if not ret:
                frame = None

        if frame is None:
            self.last_detected_text = ""
            self.is_match = False
            self.ocr_done = False
            return "", False

        self._process_frame(frame)
        return self.last_detected_text, self.is_match

    def get_preview_image(self, target_width=None, target_height=None, overlay_roi=None, overlay_color=(255, 255, 0), show_text=False):
        if self.last_frame is None:
            return None
        frame = self.last_frame.copy()
        if overlay_roi:
            x, y, w, h = overlay_roi
            cv2.rectangle(frame, (x, y), (x + w, y + h), overlay_color, 2)
        if show_text and self.current_roi and self.last_detected_text:
            x, y, w, h = self.current_roi
            cv2.putText(frame, self.last_detected_text, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, overlay_color, 2)
        if target_width and target_height and target_width > 0 and target_height > 0:
            frame = cv2.resize(frame, (int(target_width), int(target_height)), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        return ImageTk.PhotoImage(pil), self.is_match
