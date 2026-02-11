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
        
        # Reference management
        self.references = []           # list of dicts: {'name': str, 'expected_text': str, 'roi': (x,y,w,h)}
        self.current_roi = None        # currently active ROI for checking (x,y,w,h)
        self.expected_text = ""        # text we expect in the current active reference

        # Temporary ROI for live preview while dragging
        self.temp_roi = None

    def start_camera(self, camera_index=1):
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            print(f"Warning: Could not open camera index {camera_index}")
        self.is_running = self.cap.isOpened()

    def stop_camera(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.is_running = False

    def set_roi(self, x, y, w, h):
        """Set permanent ROI for checking"""
        self.current_roi = (x, y, w, h)

    def set_roi_temp(self, x, y, w, h):
        """Temporary ROI shown during mouse drag"""
        self.temp_roi = (x, y, w, h)

    def clear_roi(self):
        self.current_roi = None
        self.temp_roi = None
        self.expected_text = ""

    def set_expected_text(self, text: str):
        """Set the expected reference text for comparison"""
        self.expected_text = text.strip()

    def get_frame(self):
        if not self.is_running or self.cap is None:
            return None

        ret, frame = self.cap.read()
        if not ret:
            return None

        # Draw saved / loaded reference ROIs (green)
        for ref in self.references:
            if ref.get("roi"):
                x, y, w, h = ref["roi"]
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 100), 2)
                cv2.putText(frame, ref["name"], (x, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 100), 2)

        # Draw current active ROI (yellow/orange)
        if self.current_roi:
            x, y, w, h = self.current_roi
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 180, 255), 3)
            cv2.putText(frame, "ACTIVE", (x, y - 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 180, 255), 2)

        # Draw temporary drag rectangle (blue dashed)
        if self.temp_roi:
            x, y, w, h = self.temp_roi
            cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 120, 0), 2)
            # Optional: dashed effect simulation with lines
            for i in range(0, w, 15):
                cv2.line(frame, (x + i, y), (x + i + 8, y), (255, 120, 0), 2)
                cv2.line(frame, (x + i, y + h), (x + i + 8, y + h), (255, 120, 0), 2)
            for i in range(0, h, 15):
                cv2.line(frame, (x, y + i), (x, y + i + 8), (255, 120, 0), 2)
                cv2.line(frame, (x + w, y + i), (x + w, y + i + 8), (255, 120, 0), 2)

        # Resize for display
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)

        if pil.width > DISPLAY_WIDTH:
            ratio = DISPLAY_WIDTH / pil.width
            new_size = (DISPLAY_WIDTH, int(pil.height * ratio))
            pil = pil.resize(new_size, Image.LANCZOS)
            self.display_scale = ratio
        else:
            self.display_scale = 1.0

        return ImageTk.PhotoImage(pil)

    def check_reference(self):
        """
        Perform OCR on the current ROI and compare with expected_text
        Returns a formatted string with result
        """
        if not self.is_running or self.cap is None:
            return "Camera not running"

        if self.current_roi is None:
            return "No ROI selected"

        x, y, w, h = self.current_roi

        ret, frame = self.cap.read()
        if not ret:
            return "Failed to capture frame"

        # Crop ROI
        roi = frame[y:y+h, x:x+w]

        if roi.size == 0:
            return "Invalid ROI size"

        # Preprocessing to improve OCR accuracy
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # Optional: try adaptive threshold or simple binary
        # thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        
        # or denoising + contrast
        denoised = cv2.fastNlMeansDenoising(gray, h=10)
        enhanced = cv2.equalizeHist(denoised)

        # OCR
        try:
            # You can customize config: --psm 6 or 7 or 8 depending on text layout
            ocr_result = pytesseract.image_to_string(
                enhanced,
                config='--psm 6 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-/ '
            ).strip()
        except Exception as e:
            return f"OCR error: {str(e)}"

        if not ocr_result:
            ocr_result = "(nothing detected)"

        # Simple exact match (case insensitive)
        expected = self.expected_text.strip().lower()
        found = ocr_result.lower()

        if expected and found == expected:
            return "✅ MATCH - Reference OK"
        
        # Optional: show similarity percentage if not exact match
        similarity = SequenceMatcher(None, found, expected).ratio()
        if similarity > 0.85:
            return (f"⚠️ CLOSE MATCH ({int(similarity*100)}%)\n"
                    f"Found: {ocr_result}\n"
                    f"Expected: {self.expected_text}")
        
        return (f"❌ MISMATCH\n"
                f"Found: {ocr_result}\n"
                f"Expected: {self.expected_text}")
