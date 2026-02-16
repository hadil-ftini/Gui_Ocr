import cv2
from PIL import Image, ImageTk
import pytesseract
import numpy as np
from difflib import SequenceMatcher

DISPLAY_WIDTH = 840

class CameraApp:
    def __init__(self):
        self.cap = None
        self.is_running = False
        self.display_scale = 1.0
        self.references = []           
        self.current_roi = None        
        self.expected_text = ""        
        self.temp_roi = None

    def start_camera(self, camera_index=0):
        self.cap = cv2.VideoCapture(camera_index)
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
        return True

    def set_roi_temp(self, x, y, w, h):
        self.temp_roi = (x, y, w, h)

    def clear_roi(self):
        self.current_roi = None
        self.temp_roi = None
        self.expected_text = ""

    def get_frame(self):
        if not self.is_running or self.cap is None: return None
        ret, frame = self.cap.read()
        if not ret: return None

        # --- DRAWING LOGIC (Clean View) ---
        
        # 1. Draw Active ROI only (The one selected or just finished)
        if self.current_roi:
            x, y, w, h = self.current_roi
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 180, 255), 3)

        # 2. Draw Dragging Box (The orange preview)
        if self.temp_roi:
            tx, ty, tw, th = self.temp_roi
            cv2.rectangle(frame, (tx, ty), (tx + tw, ty + th), (255, 120, 0), 2)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        if pil.width > DISPLAY_WIDTH:
            ratio = DISPLAY_WIDTH / pil.width
            pil = pil.resize((DISPLAY_WIDTH, int(pil.height * ratio)), Image.Resampling.LANCZOS)
            self.display_scale = ratio
        else:
            self.display_scale = 1.0
        return ImageTk.PhotoImage(pil)