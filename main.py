import tkinter as tk
from tkinter import ttk
import ttkbootstrap as tb
from PIL import Image, ImageTk
import camera_module as cam
import theme_module as tm
import modbus_manager as mm
from modbus_manager import RESULT_OK, RESULT_NOK, RESULT_IDLE
import json
import os
import time
import threading
import queue


class MainApp(tb.Window):
    def __init__(self):
        super().__init__(themename="superhero")
        self.title("Check Ref - Tunitech")
        self.is_small_panel = False
        self.is_portrait_panel = False
        self._configure_responsive_window()
        self.is_portrait_panel = self._is_portrait_panel_profile()
        self.is_small_panel = self._is_small_panel_profile()
       
        self.running = True
        self.references = self.load_references()
        self.adding_new_ref = False
        self.pending_ref = None
        self.selected_reference_name = None
        self.ok_counter_var = tk.IntVar(value=0)
        self.nok_counter_var = tk.IntVar(value=0)

        # Modbus
        self.modbus_manager = mm.ModbusManager(host="127.0.0.1", port=5502)
        self.last_poll_time = 0
        self.poll_interval = 1
        self.last_plc_ref = ""
        self._modbus_was_connected = False
        self.modbus_enabled = True

        # Virtual Keyboard
        self.keyboard_win = None
        self.current_kb_entry = None
        self.current_kb_var = None
        self.current_next_widget = None
        self._closing_keyboard = False

        self.setup_ui()
       
        self.camera = cam.CameraApp()
        self.camera_width = 1 # Initialize with dummy values
        self.camera_height = 1 # Initialize with dummy values
        self._roi_dragging = False
        self.main_camera_display = True

        # Threading setup
        self.modbus_queue = queue.Queue()
        self.modbus_write_queue = queue.Queue()  # Separate queue for write operations
        self.camera_queue = queue.Queue()
        self.modbus_thread = None
        self.camera_thread = None
        self._start_background_tasks() # Start background processing threads
        self.update_gui_from_queues() # Start the GUI update loop

        # Track whether an OCR test is currently running
        self._test_in_progress = False

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.bind("<Configure>", self._on_main_window_configure)

    def _screen_size(self):
        return self.winfo_screenwidth(), self.winfo_screenheight()

    def _is_portrait_panel_profile(self):
        """Return True for 7-inch portrait panels (~154mm H x 86mm W, 480x800)."""
        screen_w, screen_h = self._screen_size()
        if screen_w == 450 and screen_h == 700:
            return True
        return screen_h > screen_w and screen_w <= 520 and screen_h >= 700

    def _is_hd_portrait_panel(self):
        """Return True for 720x1280 HD portrait displays."""
        screen_w, screen_h = self._screen_size()
        if screen_w == 720 and screen_h == 1280:
            return True
        return screen_h > screen_w and screen_w == 720 and screen_h >= 1200

    def _is_landscape_panel_profile(self):
        """Return True for 7-inch landscape panels (800x480)."""
        screen_w, screen_h = self._screen_size()
        if screen_w == 700 and screen_h == 450:
            return True
        return screen_w > screen_h and screen_w <= 820 and screen_h <= 520

    def _is_embedded_panel(self):
        """Any small Raspberry Pi / 7-inch embedded display."""
        return self._is_portrait_panel_profile() or self._is_landscape_panel_profile() or self._is_hd_portrait_panel()

    def _is_small_panel_profile(self):
        """Return True for Raspberry Pi / 7-inch style displays (landscape or portrait)."""
        return self._is_embedded_panel()

    def _is_hd_panel(self):
        """Return True for HD portrait panels (720x1280)."""
        return self._is_hd_portrait_panel()

    def _embedded_sidebar_width(self):
        if self.is_portrait_panel or self._is_hd_portrait_panel():
            return 0
        return 175 if self._is_landscape_panel_profile() else 200

    def _responsive_font(self, base_size, bold=False):
        """Scale fonts for small embedded panels and touch usage."""
        if self._is_hd_portrait_panel():
            scale = 1.10  # Slightly larger for 720x1280
        elif self.is_portrait_panel:
            scale = 0.95
        elif self._is_landscape_panel_profile():
            scale = 0.88
        elif self.is_small_panel:
            scale = 1.05
        else:
            scale = 1.0
        weight = "bold" if bold else "normal"
        return ("Helvetica", max(8, int(base_size * scale)), weight)

    def _lock_fullscreen_window(self, win_w, win_h):
        """Fill the physical panel and prevent resize drift on embedded displays."""
        self.geometry(f"{win_w}x{win_h}+0+0")
        self.minsize(win_w, win_h)
        try:
            self.resizable(False, False)
        except Exception:
            pass

    def _configure_responsive_window(self):
        """Initialize window geometry for the current display."""
        screen_w, screen_h = self._screen_size()
        if self._is_embedded_panel():
            self._lock_fullscreen_window(screen_w, screen_h)
            return

        win_w = int(screen_w * 0.96)
        win_h = int(screen_h * 0.90)
        win_w = min(win_w, screen_w)
        win_h = min(win_h, screen_h)
        pos_x = max(0, (screen_w - win_w) // 2)
        pos_y = max(0, (screen_h - win_h) // 2)
        self.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        self.minsize(640, 420)
        self.resizable(True, True)

    def on_closing(self):
        """Handles graceful shutdown of the application."""
        print("Closing application...")
        self.running = False 
        if self.modbus_thread and self.modbus_thread.is_alive():
            self.modbus_thread.join(timeout=1)
        if self.camera_thread and self.camera_thread.is_alive():
            self.camera_thread.join(timeout=1)

        if self.modbus_manager:
            self.modbus_manager.disconnect()
        if self.camera:
            self.camera.stop_camera()
        self.destroy()

    def update_result_ui(self, text, bootstyle):
        """Updates only the UI result label."""
        self.result_label.configure(text=text, bootstyle=bootstyle)

    def update_ocr_text(self, detected_text):
        pass

    def _preview_to_frame_roi(self, roi, preview_size):
        if not roi or self.camera.last_frame is None:
            return None
        frame_h, frame_w = self.camera.last_frame.shape[:2]
        preview_w, preview_h = preview_size
        x, y, w, h = roi
        sx = frame_w / preview_w
        sy = frame_h / preview_h
        return (int(x * sx), int(y * sy), int(w * sx), int(h * sy))

    def _frame_to_preview_roi(self, roi, preview_size):
        if not roi or self.camera.last_frame is None:
            return None
        frame_h, frame_w = self.camera.last_frame.shape[:2]
        preview_w, preview_h = preview_size
        x, y, w, h = roi
        sx = preview_w / frame_w
        sy = preview_h / frame_h
        return (int(x * sx), int(y * sy), int(w * sx), int(h * sy))

    def _create_live_preview(self, parent, width=520, height=300, initial_roi=None, expand_preview=False):
        pad = 4 if self._is_embedded_panel() else 10
        preview_container = tb.Frame(parent)
        if expand_preview:
            preview_container.grid(row=0, column=0, sticky="nsew", padx=pad, pady=pad)
        else:
            preview_container.pack(padx=pad, pady=pad, fill="both", expand=True)
        preview_label = tb.Label(preview_container, cursor="crosshair")
        preview_label.pack(fill="both", expand=True)
        preview_label.preview_size = (width, height)
        scaled_roi = self._frame_to_preview_roi(initial_roi, preview_label.preview_size) if initial_roi else None
        preview_label.local_roi = scaled_roi
        preview_label.temp_roi = scaled_roi
        preview_label.rect_start = None

        def on_down(event):
            preview_label.rect_start = (event.x, event.y)
            preview_label.local_roi = None
            preview_label.temp_roi = None

        def on_drag(event):
            if not preview_label.rect_start:
                return
            start_x, start_y = preview_label.rect_start
            curr_x, curr_y = event.x, event.y
            x0, y0 = min(start_x, curr_x), min(start_y, curr_y)
            w0, h0 = abs(curr_x - start_x), abs(curr_y - start_y)
            preview_label.temp_roi = (x0, y0, w0, h0)
            self._refresh_preview(preview_label)

        def on_up(event):
            if not preview_label.rect_start:
                return
            if preview_label.temp_roi:
                preview_label.local_roi = preview_label.temp_roi
            preview_label.rect_start = None
            self._refresh_preview(preview_label)

        preview_label.bind("<Button-1>", on_down)
        preview_label.bind("<B1-Motion>", on_drag)
        preview_label.bind("<ButtonRelease-1>", on_up)

        def refresh_loop():
            self._refresh_preview(preview_label)
            preview_label.after(50, refresh_loop)

        refresh_loop()
        return preview_label

    def _refresh_preview(self, preview_label):
        if not preview_label.winfo_exists():
            return
        overlay_roi = preview_label.temp_roi or preview_label.local_roi
        if overlay_roi:
            overlay_roi = self._preview_to_frame_roi(overlay_roi, preview_label.preview_size)
        img, _ = self.camera.get_preview_image(
            target_width=preview_label.preview_size[0],
            target_height=preview_label.preview_size[1],
            overlay_roi=overlay_roi,
            overlay_color=(255, 255, 0),
            show_text=False
        )
        if img:
            preview_label.configure(image=img)
            preview_label.image = img

    def _ref_label_text(self, name=None):
        prefix = "Ref:" if self.is_portrait_panel else "Reference:"
        return f"{prefix} {name}" if name else f"{prefix} None"

    def _preview_dimensions(self, default_w=580, default_h=300):
        screen_w, screen_h = self._screen_size()
        if self._is_hd_portrait_panel():
            return screen_w - 20, max(300, int(screen_h * 0.28))
        if self.is_portrait_panel:
            return screen_w - 16, max(140, int(screen_h * 0.22))
        if self._is_landscape_panel_profile():
            return screen_w - self._embedded_sidebar_width() - 30, max(220, int(screen_h * 0.58))
        return default_w, default_h

    def _tree_column_widths(self, total_width=None):
        """Split treeview columns layout effectively."""
        if total_width is None:
            total_width = self._screen_size()[0]
        usable = max(200, total_width - 50)
        if usable < 500:
            return int(usable * 0.42), int(usable * 0.58)
        return int(usable * 0.35), int(usable * 0.65)

    def _update_reference_counters(self, match=None):
        selected_ref = next((r for r in self.references if r['name'] == self.selected_reference_name), None)
        if selected_ref is not None:
            if match is True:
                selected_ref['ok_count'] = selected_ref.get('ok_count', 0) + 1
            elif match is False:
                selected_ref['nok_count'] = selected_ref.get('nok_count', 0) + 1
            self.ok_counter_var.set(selected_ref.get('ok_count', 0))
            self.nok_counter_var.set(selected_ref.get('nok_count', 0))
            if hasattr(self, 'ok_label'):
                self.ok_label.configure(text=f"OK: {selected_ref.get('ok_count', 0)}")
            if hasattr(self, 'nok_label'):
                self.nok_label.configure(text=f"NOK: {selected_ref.get('nok_count', 0)}")
            if hasattr(self, 'selected_ref_label'):
                self.selected_ref_label.configure(text=self._ref_label_text(selected_ref['name']))
            self.save_references()
        else:
            self.ok_counter_var.set(0)
            self.nok_counter_var.set(0)
            if hasattr(self, 'ok_label'):
                self.ok_label.configure(text="OK: 0")
            if hasattr(self, 'nok_label'):
                self.nok_label.configure(text="NOK: 0")
            if hasattr(self, 'selected_ref_label'):
                self.selected_ref_label.configure(text=self._ref_label_text())

    def _clear_ocr_results(self):
        self.update_result_ui("Ready", "info")

    def _load_logo(self, path, height):
        """Load and resize a logo for the header bar safely."""
        try:
            logo_img = Image.open(path)
            aspect = logo_img.width / logo_img.height
            new_width = max(45, int(height * aspect))
            logo_img = logo_img.resize((new_width, height), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(logo_img)
        except Exception:
            return None

    def _build_header_controls(self, parent, combo_width=16):
        """Shared reference combo + action buttons for compact headers."""
        self.ref_var = tk.StringVar()
        self.ref_combo = tb.Combobox(parent, textvariable=self.ref_var,
                                     values=[r['name'] for r in self.references],
                                     state="readonly", width=combo_width)
        self.ref_combo.configure(font=self._responsive_font(9))
        self.ref_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.ref_combo.bind("<<ComboboxSelected>>", self.on_ref_selected)

        btn_pad = (3, 2) if self._is_landscape_panel_profile() else (4, 3)
        self.modbus_btn = tb.Button(parent, text="Modbus", bootstyle="success",
                                    command=self.toggle_modbus, padding=btn_pad)
        self.modbus_btn.pack(side="right", padx=2)
        self.test_btn = tb.Button(parent, text="Test", bootstyle="success",
                                  command=self.test_ocr, padding=btn_pad)
        self.test_btn.pack(side="right", padx=2)

    def setup_ui(self):
        portrait = self.is_portrait_panel
        hd_portrait = self._is_hd_portrait_panel()
        landscape_small = self._is_landscape_panel_profile()
        small = self.is_small_panel and not portrait and not hd_portrait
        project_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(project_dir, "logo.png")
        logo2_path = os.path.join(project_dir, "logo2.png")
        button_pad = (6, 4) if small else (4, 2)
        logo_h = 20 if landscape_small else (28 if hd_portrait else (22 if portrait else 45))

        if portrait or hd_portrait:
            self.grid_rowconfigure(0, weight=0)
            self.grid_rowconfigure(1, weight=1)
            self.grid_rowconfigure(2, weight=0)
            self.grid_columnconfigure(0, weight=1)
        else:
            self.grid_rowconfigure(0, weight=0)
            self.grid_rowconfigure(1, weight=1)
            self.grid_columnconfigure(0, weight=0)
            self.grid_columnconfigure(1, weight=1)

        # ─── Header ───
        self.header = tb.Frame(self, bootstyle="light")
        header_span = 1 if (portrait or hd_portrait) else 2
        self.header.grid(row=0, column=0, columnspan=header_span, sticky="ew", padx=0, pady=0)

        if portrait or hd_portrait or small:
            pad_x = 4 if portrait else (5 if hd_portrait else 5)
            top_bar = tb.Frame(self.header, bootstyle="light")
            top_bar.pack(fill="x", padx=pad_x, pady=(3, 2))

            logo_tk = self._load_logo(logo_path, logo_h)
            if logo_tk:
                self.logo_tk = logo_tk
                self.logo_label = tb.Label(top_bar, image=self.logo_tk, bootstyle="light")
                self.logo_label.pack(side="left")
            else:
                self.logo_label = tb.Label(top_bar, text="TUNITECH",
                                           font=self._responsive_font(10, True), bootstyle="light")
                self.logo_label.pack(side="left")

            if not landscape_small:
                logo2_tk = self._load_logo(logo2_path, logo_h)
                if logo2_tk:
                    self.logo2_tk = logo2_tk
                    self.logo2_label = tb.Label(top_bar, image=self.logo2_tk, bootstyle="light")
                    self.logo2_label.pack(side="right")

            controls = tb.Frame(self.header, bootstyle="light")
            controls.pack(fill="x", padx=pad_x, pady=(0, 3))
            combo_w = 12 if portrait else (16 if hd_portrait else 16)
            self._build_header_controls(controls, combo_width=combo_w)
        else:
            self.header.columnconfigure(1, weight=1)
            self.header.columnconfigure(2, weight=1)
            self.header.columnconfigure(3, weight=0)
            self.header.columnconfigure(4, weight=0)
            self.header.columnconfigure(5, weight=0)
            self.header.columnconfigure(6, weight=0)

            logo_tk = self._load_logo(logo_path, logo_h)
            if logo_tk:
                self.logo_tk = logo_tk
                self.logo_label = tb.Label(self.header, image=self.logo_tk)
                self.logo_label.grid(row=0, column=0, padx=15, pady=8, sticky="w")
            else:
                self.logo_label = tb.Label(self.header, text="TUNITECH", font=self._responsive_font(18, True))
                self.logo_label.grid(row=0, column=0, padx=15, pady=8, sticky="w")

            logo2_tk = self._load_logo(logo2_path, logo_h)
            if logo2_tk:
                self.logo2_tk = logo2_tk
                self.logo2_label = tb.Label(self.header, image=self.logo2_tk)
                self.logo2_label.grid(row=0, column=6, padx=15, pady=8, sticky="e")

            self.modbus_btn = tb.Button(self.header, text="🔌 Modbus: ON", bootstyle="success", command=self.toggle_modbus,
                                        padding=button_pad)
            self.modbus_btn.grid(row=0, column=4, padx=15, pady=8, sticky="e")

            self.test_btn = tb.Button(self.header, text="Test", bootstyle="success", command=self.test_ocr,
                                      padding=button_pad)
            self.test_btn.grid(row=0, column=5, padx=15, pady=8, sticky="e")

            self.ref_var = tk.StringVar()
            self.ref_combo = tb.Combobox(self.header, textvariable=self.ref_var,
                                         values=[r['name'] for r in self.references],
                                         state="readonly", width=28)
            self.ref_combo.configure(font=self._responsive_font(10))
            self.ref_combo.grid(row=0, column=2, padx=15, pady=8, sticky="e")
            self.ref_combo.bind("<<ComboboxSelected>>", self.on_ref_selected)

        # ─── Sidebar (landscape small / desktop only) ───
        if not portrait:
            sidebar_w = self._embedded_sidebar_width()
            self.sidebar = tb.Frame(self, bootstyle="dark")
            self.sidebar.grid(row=1, column=0, sticky="nsw", padx=0, pady=0)
            if small:
                self.sidebar.configure(width=sidebar_w)
                self.sidebar.grid_propagate(False)

            sidebar_inner = tb.Frame(self.sidebar, bootstyle="dark")
            sidebar_inner.pack(padx=6 if small else 10, pady=8 if small else 10, fill="both", expand=True)

            ref_btn_text = "⚙ Ref Mgmt" if small else "⚙ Reference Management"
            tb.Button(sidebar_inner, text=ref_btn_text, bootstyle="success",
                      command=self.open_reference_management,
                      padding=(4, 3) if small else (6, 4)).pack(pady=6 if small else 8, fill="x")
            self.selected_ref_label = tb.Label(sidebar_inner, text=self._ref_label_text(),
                                               font=self._responsive_font(10, True), bootstyle="secondary")
            self.selected_ref_label.pack(pady=(8, 4), fill="x")
            self.ok_label = tb.Label(sidebar_inner, text="OK: 0",
                                     font=self._responsive_font(13 if landscape_small else 14, True), bootstyle="success")
            self.ok_label.pack(pady=2, fill="x")
            self.nok_label = tb.Label(sidebar_inner, text="NOK: 0",
                                      font=self._responsive_font(13 if landscape_small else 14, True), bootstyle="danger")
            self.nok_label.pack(pady=2, fill="x")

        # ─── Main Content ───
        content_col = 0 if (portrait or hd_portrait) else 1
        if portrait or hd_portrait:
            content_pad = (2, 0) if portrait else (4, 3)
        elif landscape_small:
            content_pad = (3, 3)
        elif small:
            content_pad = (4, 4)
        else:
            content_pad = (10, 10)
        self.main_content = tb.Frame(self)
        self.main_content.grid(row=1, column=content_col, sticky="nsew", padx=content_pad[0], pady=content_pad[1])

        self.main_content.grid_rowconfigure(0, weight=1)
        self.main_content.grid_rowconfigure(1, weight=0)
        self.main_content.grid_columnconfigure(0, weight=1)

        self.camera_frame = tb.Labelframe(self.main_content, text="Live Feed")
        self.camera_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.camera_label = tb.Label(self.camera_frame, cursor="arrow")
        self.camera_label.pack(fill="both", expand=True)

        self.result_label = tb.Label(self.main_content, text="Ready",
                                     font=self._responsive_font(13 if landscape_small else (14 if hd_portrait else (12 if portrait else 14)), True),
                                     bootstyle="info", anchor="center")
        result_pady = 6 if landscape_small else (8 if hd_portrait else (6 if portrait else 10))
        self.result_label.grid(row=1, column=0, sticky="ew", pady=result_pady)

        # ─── Footer bar (portrait only) ───
        if portrait or hd_portrait:
            self.footer = tb.Frame(self, bootstyle="dark")
            self.footer.grid(row=2, column=0, sticky="ew", padx=0, pady=0)

            footer_top = tb.Frame(self.footer, bootstyle="dark")
            footer_top.pack(fill="x", padx=6, pady=(4, 2))
            tb.Button(footer_top, text="⚙ Ref Mgmt", bootstyle="success", command=self.open_reference_management,
                      padding=(4, 3)).pack(side="left")
            self.selected_ref_label = tb.Label(footer_top, text=self._ref_label_text(), font=self._responsive_font(9, True),
                                             bootstyle="secondary", anchor="w")
            self.selected_ref_label.pack(side="left", fill="x", expand=True, padx=(6, 0))

            footer_stats = tb.Frame(self.footer, bootstyle="dark")
            footer_stats.pack(fill="x", padx=6, pady=(0, 4))
            self.ok_label = tb.Label(footer_stats, text="OK: 0", font=self._responsive_font(12, True), bootstyle="success")
            self.ok_label.pack(side="left", expand=True, fill="x")
            self.nok_label = tb.Label(footer_stats, text="NOK: 0", font=self._responsive_font(12, True), bootstyle="danger")
            self.nok_label.pack(side="right", expand=True, fill="x")

        self.camera_label.bind("<Configure>", self._on_camera_label_configure)
        self.camera_label.bind("<Button-1>", self.on_mouse_down)
        self.camera_label.bind("<B1-Motion>", self.on_mouse_drag)
        self.camera_label.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.rect_start = None

    def test_ocr(self):
        self._run_selected_reference_test(show_dialog_on_error=True)

    def _run_selected_reference_test(self, show_dialog_on_error=False):
        """Run OCR test on currently selected reference and write result to PLC."""
        ref_name = self.ref_var.get().strip()
        selected_ref = next((r for r in self.references if r['name'] == ref_name), None)
        if not selected_ref:
            self.update_result_ui("FAIL: No Active Reference", "danger")
            if show_dialog_on_error:
                tb.dialogs.Messagebox.show_warning("Please select a reference first.", title="Reference Required", parent=self)
            return False

        self.camera.set_roi(*selected_ref['roi'])
        self.camera.expected_text = selected_ref['expected_text']
        self.camera.last_detected_text = ""
        self.camera.is_match = False
        self.camera.ocr_done = False

        if not self.camera.current_roi or not self.camera.expected_text:
            self.update_result_ui("FAIL: No Active Reference", "danger")
            if show_dialog_on_error:
                tb.dialogs.Messagebox.show_warning("The selected reference has no ROI or expected text.", title="Reference Required", parent=self)
            return False

        detected, match = self.camera.perform_ocr_once()
        if match:
            self.update_result_ui("OK", "success")
            self.modbus_write_queue.put({"type": "write_result", "value": RESULT_OK})
        else:
            self.update_result_ui("NOK", "danger")
            self.modbus_write_queue.put({"type": "write_result", "value": RESULT_NOK})
        self._update_reference_counters(match)
        return True

    # ─── VIRTUAL KEYBOARD SYSTEM ───
    def show_virtual_keyboard(self, entry, next_widget=None, kb_var=None):
        if self._closing_keyboard:
            return
        self.current_kb_entry = entry
        self.current_kb_var = kb_var
        self.current_next_widget = next_widget
        parent_win = entry.winfo_toplevel()

        if self.keyboard_win and self.keyboard_win.winfo_exists():
            self._close_keyboard()

        self.keyboard_win = tb.Toplevel(parent_win)
        self.keyboard_win.title("Keyboard")

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        portrait_profile = self.is_portrait_panel
        hd_portrait = self._is_hd_portrait_panel()
        landscape_embedded = self._is_landscape_panel_profile()

        kb_width = screen_w
        if portrait_profile:
            kb_height = max(200, int(screen_h * 0.30))
            x, y = 0, max(0, screen_h - kb_height)
        elif hd_portrait:
            kb_height = max(280, int(screen_h * 0.28))
            x, y = 0, max(0, screen_h - kb_height)
        elif landscape_embedded:
            kb_height = max(220, int(screen_h * 0.36))
            x, y = 0, max(0, screen_h - kb_height - 2)
        else:
            kb_width = min(900, int(screen_w * 0.75))
            kb_height = 350
            x = max(0, (screen_w - kb_width) // 2)
            y = max(0, screen_h - kb_height - 50)
        self.keyboard_win.geometry(f"{kb_width}x{kb_height}+{x}+{y}")

        self.keyboard_win.attributes("-topmost", True)
        self.keyboard_win.resizable(True, True)
        self.keyboard_win.protocol("WM_DELETE_WINDOW", self._close_keyboard)
        self.keyboard_win.transient(parent_win)
        self.keyboard_win.bind("<Destroy>", lambda e: self._close_keyboard() if e.widget == self.keyboard_win else None)
        try:
            self.keyboard_win.attributes("-toolwindow", 1)
        except tk.TclError:
            pass

        self.keyboard_win.lift()
        self._build_keyboard_layout()
        entry.focus_set()

    def _close_keyboard(self):
        self._closing_keyboard = True
        if self.keyboard_win and self.keyboard_win.winfo_exists():
            self.keyboard_win.destroy()
        self.keyboard_win = None
        self.current_kb_entry = None
        self.current_kb_var = None
        self.current_next_widget = None
        self._closing_keyboard = False

    def _create_child_window(self, title, width, height, parent=None, resizable=(True, True), center=True, fullscreen=False):
        if parent is None:
            parent = self
        screen_width, screen_height = self._screen_size()
        embedded = self._is_embedded_panel()

        if fullscreen and embedded:
            if self._is_landscape_panel_profile():
                width, height = 780, 440
            else:
                width, height = screen_width, screen_height
            x, y = 0, 0
            center = False
            resizable = (False, False)
        elif embedded:
            width = min(width, screen_width)
            height = min(height, screen_height)
            x = max(0, (screen_width - width) // 2)
            y = max(0, (screen_height - height) // 2)
            center = False
        else:
            x = max(0, (screen_width - width) // 2)
            y = max(0, (screen_height - height) // 2)

        win = tb.Toplevel(parent)
        win.title(title)
        win.geometry(f"{width}x{height}+{x}+{y}")
        win.resizable(*resizable)
        if fullscreen and embedded:
            win.minsize(width, height)
        win.transient(parent)
        win.attributes("-topmost", True)
        win.lift()
        win.focus_force()
        win.after(200, lambda: win.attributes("-topmost", False))
        return win

    def _build_management_buttons(self, parent, close_cmd):
        """Action buttons sized cleanly for management view panels."""
        screen_w = self._screen_size()[0]
        btn_pad = (3, 2) if screen_w <= 520 else (10, 4)
        buttons = [
            ("Add", "success", self._add_reference),
            ("Edit", "warning", self._edit_reference),
            ("Remove", "danger", self._remove_reference),
            ("Close", "secondary", close_cmd),
        ]
        if screen_w <= 520:
            parent.columnconfigure(0, weight=1)
            parent.columnconfigure(1, weight=1)
            for i, (text, style, cmd) in enumerate(buttons):
                tb.Button(parent, text=text, bootstyle=style, command=cmd, padding=btn_pad).grid(
                    row=i // 2, column=i % 2, sticky="ew", padx=3, pady=2)
        else:
            for text, style, cmd in buttons:
                tb.Button(parent, text=text, bootstyle=style, command=cmd, padding=btn_pad).pack(side="left", padx=6)

    def _build_ref_form_window(self, win, name_var, text_var, save_text, save_cmd):
        """Compact form layout for adding/editing reference configurations."""
        embedded = self._is_embedded_panel()
        win.grid_rowconfigure(0, weight=1)
        win.grid_rowconfigure(1, weight=0)
        win.grid_columnconfigure(0, weight=1)

        form_pad = 6 if embedded else 15
        container = tb.Frame(win, padding=form_pad)
        container.grid(row=1, column=0, sticky="ew")
        container.grid_columnconfigure(0, weight=1)

        lbl_font = self._responsive_font(10, True) if embedded else ("Helvetica", 12, "bold")
        entry_font = self._responsive_font(11) if embedded else ("Helvetica", 14)
        entry_pady = (0, 6) if embedded else (0, 15)

        tb.Label(container, text="Reference Name:", font=lbl_font).grid(row=0, column=0, sticky="w", pady=(0, 2))
        e1 = tb.Entry(container, textvariable=name_var, font=entry_font)
        e1.grid(row=1, column=0, sticky="ew", pady=entry_pady)

        tb.Label(container, text="Expected Text:", font=lbl_font).grid(row=2, column=0, sticky="w", pady=(0, 2))
        e2 = tb.Entry(container, textvariable=text_var, font=entry_font)
        e2.grid(row=3, column=0, sticky="ew", pady=entry_pady)

        def trigger_e1(e):
            e1.focus_set()
            e1.icursor(tk.END)
            self.after(100, lambda: self.show_virtual_keyboard(e1, e2, name_var))
        def trigger_e2(e):
            e2.focus_set()
            e2.icursor(tk.END)
            self.after(100, lambda: self.show_virtual_keyboard(e2, None, text_var))
        e1.bind("<Button-1>", trigger_e1)
        e2.bind("<Button-1>", trigger_e2)

        tb.Button(container, text=save_text, bootstyle="success-outline", command=save_cmd,
                  padding=(4, 3) if embedded else (6, 4)).grid(row=4, column=0, sticky="ew", pady=(2, 4))
        return e1, e2

    def _pause_main_camera_display(self):
        self.main_camera_display = False
        try:
            self.camera_label.configure(image="")
            self.camera_label.image = None
            self.camera_label.configure(text="Main camera paused", bootstyle="secondary")
        except Exception:
            pass

    def _resume_main_camera_display(self):
        self.main_camera_display = True
        try:
            self.camera_label.configure(text="")
        except Exception:
            pass

    def _show_top_message(self, title, message, width=380, height=150):
        popup = tb.Toplevel(self)
        popup.title(title)
        screen_width = popup.winfo_screenwidth()
        screen_height = popup.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.resizable(False, False)
        popup.transient(self)
        popup.attributes("-topmost", True)
        popup.lift()
        popup.focus_force()
        container = tb.Frame(popup, padding=15)
        container.pack(fill="both", expand=True)
        tb.Label(container, text=message, wraplength=width - 30, font=("Helvetica", 12), bootstyle="success", anchor="center", justify="center").pack(fill="both", expand=True, pady=(0, 10))
        tb.Button(container, text="OK", bootstyle="primary", command=popup.destroy).pack(pady=(0, 5))
        return popup

    def _kb_key(self, char):
        if self.current_kb_entry and self.current_kb_entry.winfo_exists():
            self.current_kb_entry.insert(tk.END, char)

    def _kb_backspace(self):
        if self.current_kb_entry and self.current_kb_entry.winfo_exists():
            txt = self.current_kb_entry.get()
            self.current_kb_entry.delete(0, tk.END)
            self.current_kb_entry.insert(0, txt[:-1] if txt else "")

    def _kb_clear(self):
        if self.current_kb_entry and self.current_kb_entry.winfo_exists():
            self.current_kb_entry.delete(0, tk.END)

    def _kb_enter(self):
        if self.current_next_widget and self.current_next_widget.winfo_exists():
            self.current_next_widget.focus_set()
            self.after(50, lambda: self.show_virtual_keyboard(
                self.current_next_widget, None, getattr(self.current_next_widget, "associated_var", None)
            ))
        else:
            self._close_keyboard()

    def _build_keyboard_layout(self):
        if not self.keyboard_win or not self.keyboard_win.winfo_exists():
            return
        for widget in self.keyboard_win.winfo_children():
            widget.destroy()
        main_frame = tb.Frame(self.keyboard_win)
        hd_portrait = self._is_hd_portrait_panel()
        kb_outer_pad = (4, 4) if self.is_portrait_panel else (5, 5) if hd_portrait else (10, 10)
        main_frame.pack(expand=True, fill="both", padx=kb_outer_pad[0], pady=kb_outer_pad[1])
        keys = [['1','2','3','4','5','6','7','8','9','0'],
                ['q','w','e','r','t','y','u','i','o','p'],
                ['a','s','d','f','g','h','j','k','l'],
                ['z','x','c','v','b','n','m']]
        compact_profile = self._is_embedded_panel()
        key_font = self._responsive_font(9, True) if compact_profile else ("Helvetica", 11, "bold")
        button_pad_x = 1 if compact_profile else 2
        button_pad_y = 1 if compact_profile else 2
        key_btn_pad = (1, 1) if self.is_portrait_panel else ((2, 2) if hd_portrait else ((2, 1) if compact_profile else (3, 2)))
        for i in range(len(keys) + 1):
            main_frame.grid_rowconfigure(i, weight=1)
        for i in range(10):
            main_frame.grid_columnconfigure(i, weight=1)
        for r_idx, row_keys in enumerate(keys):
            col_offset = (10 - len(row_keys)) // 2
            for c_idx, key in enumerate(row_keys):
                btn = tb.Button(main_frame, text=key.upper(), command=lambda k=key: self._kb_key(k), takefocus=0, font=key_font, padding=key_btn_pad)
                btn.grid(row=r_idx, column=c_idx + col_offset, sticky="nsew", padx=button_pad_x, pady=button_pad_y)
        bottom_row_idx = len(keys)
        bottom_frame = tb.Frame(main_frame)
        bottom_frame.grid(row=bottom_row_idx, column=0, columnspan=10, sticky="ew", pady=(4 if self.is_portrait_panel else (5 if hd_portrait else 8), 0))
        bottom_frame.grid_columnconfigure(0, weight=2)
        bottom_frame.grid_columnconfigure(1, weight=5)
        bottom_frame.grid_columnconfigure(2, weight=2)
        bottom_frame.grid_columnconfigure(3, weight=2)
        bottom_frame.grid_columnconfigure(4, weight=2)
        special_pad = (2, 1) if compact_profile else ((2, 2) if hd_portrait else (4, 2))
        tb.Button(bottom_frame, text="Enter", bootstyle="success", command=self._kb_enter, takefocus=0, font=key_font, padding=special_pad).grid(row=0, column=0, sticky="nsew", padx=2, pady=1)
        tb.Button(bottom_frame, text="Space", command=lambda: self._kb_key(" "), takefocus=0, font=key_font, padding=special_pad).grid(row=0, column=1, sticky="nsew", padx=2, pady=1)
        tb.Button(bottom_frame, text="⌫", bootstyle="warning", command=self._kb_backspace, takefocus=0, font=key_font, padding=special_pad).grid(row=0, column=2, sticky="nsew", padx=2, pady=1)
        tb.Button(bottom_frame, text="Clear", bootstyle="danger", command=self._kb_clear, takefocus=0, font=key_font, padding=special_pad).grid(row=0, column=3, sticky="nsew", padx=2, pady=1)
        tb.Button(bottom_frame, text="Close", bootstyle="secondary", command=self._close_keyboard, takefocus=0, font=key_font, padding=special_pad).grid(row=0, column=4, sticky="nsew", padx=2, pady=1)

    # ─── REFERENCE MANAGEMENT ───
    def open_reference_management(self):
        pw_w = min(280, self._screen_size()[0] - 20)
        pw_h = 130 if self._is_embedded_panel() else 150
        password_win = self._create_child_window("Enter Password", pw_w, pw_h, parent=self, resizable=(False, False))
        tb.Label(password_win, text="Password:", font=("Helvetica", 12)).pack(pady=10)
        password_var = tk.StringVar()
        password_entry = tb.Entry(password_win, textvariable=password_var, show="*", font=("Helvetica", 14))
        password_entry.pack(pady=5)

        def check_password():
            if password_var.get().strip().upper() == "TUNITECH":
                password_win.destroy()
                self._open_management_window()
            else:
                tb.dialogs.Messagebox.show_error("Incorrect password, please try again.", title="Error", parent=password_win)

        def on_enter(event):
            check_password()
        password_entry.bind("<Return>", on_enter)
        password_entry.bind("<Button-1>", lambda e: self.show_virtual_keyboard(password_entry, None, password_var))
        tb.Button(password_win, text="Enter", bootstyle="success", command=check_password).pack(pady=10)

    def _open_management_window(self):
        win_w = 715 if self._is_hd_portrait_panel() else 720
        win_h = 800 if self._is_hd_portrait_panel() else 520
        self.mgmt_win = self._create_child_window("Reference Management", win_w, win_h, fullscreen=True)
        self._pause_main_camera_display()

        # Set up a responsive grid structure for the Management Frame layout
        self.mgmt_win.grid_rowconfigure(0, weight=1)
        self.mgmt_win.grid_rowconfigure(1, weight=0)
        self.mgmt_win.grid_columnconfigure(0, weight=1)

        main_panel = tb.Frame(self.mgmt_win, padding=10)
        main_panel.grid(row=0, column=0, sticky="nsew")
        main_panel.grid_columnconfigure(0, weight=1)
        main_panel.grid_rowconfigure(0, weight=1)

        # Left / Top side List components
        list_frame = tb.Labelframe(main_panel, text="Saved References", padding=5)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)

        columns = ("name", "text")
        self.tree = tb.Treeview(list_frame, columns=columns, show="headings", bootstyle="primary")
        self.tree.heading("name", text="Ref Name")
        self.tree.heading("text", text="Expected String Alignment")
        
        # Calculate dynamic column width allocation rules
        w_name, w_text = self._tree_column_widths(win_w)
        self.tree.column("name", width=w_name, anchor="w")
        self.tree.column("text", width=w_text, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = tb.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Layout operation buttons
        btn_container = tb.Frame(self.mgmt_win, padding=10)
        btn_container.grid(row=1, column=0, sticky="ew", pady=5)
        
        def close_mgmt():
            self._resume_main_camera_display()
            self._close_keyboard()
            self.mgmt_win.destroy()

        self._build_management_buttons(btn_container, close_mgmt)
        self._populate_reference_tree()

    def _populate_reference_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for ref in self.references:
            self.tree.insert("", "end", values=(ref['name'], ref['expected_text']))

    def _add_reference(self):
        self._open_reference_form("Add New Reference", "", "", self._save_new_reference)

    def _edit_reference(self):
        selected = self.tree.selection()
        if not selected:
            tb.dialogs.Messagebox.show_warning("Please select a reference entry to modify.", title="No Selection", parent=self.mgmt_win)
            return
        item_vals = self.tree.item(selected[0], "values")
        self._open_reference_form(f"Edit: {item_vals[0]}", item_vals[0], item_vals[1], self._save_edited_reference)

    def _open_reference_form(self, title, name, text, save_callback):
        form_win = self._create_child_window(title, 420, 310, parent=self.mgmt_win, resizable=(False, False))
        name_var = tk.StringVar(value=name)
        text_var = tk.StringVar(value=text)

        def on_save():
            if save_callback(name_var.get().strip(), text_var.get().strip(), name):
                form_win.destroy()
                self._populate_reference_tree()

        self._build_ref_form_window(form_win, name_var, text_var, "Save Reference Pattern", on_save)

    def _save_new_reference(self, name, text, original_name=None):
        if not name or not text:
            tb.dialogs.Messagebox.show_error("Fields cannot be left blank.", title="Validation Error", parent=self.mgmt_win)
            return False
        if any(r['name'].upper() == name.upper() for r in self.references):
            tb.dialogs.Messagebox.show_error("A unique reference configuration pattern already exists.", title="Duplicate Error", parent=self.mgmt_win)
            return False
        
        self.references.append({
            "name": name, "expected_text": text, "roi": [50, 50, 150, 80],
            "ok_count": 0, "nok_count": 0
        })
        self.save_references()
        self._update_combo_options()
        return True

    def _save_edited_reference(self, name, text, original_name):
        if not name or not text:
            tb.dialogs.Messagebox.show_error("Fields cannot be empty.", title="Validation Error", parent=self.mgmt_win)
            return False
        
        ref = next((r for r in self.references if r['name'] == original_name), None)
        if ref:
            ref['name'] = name
            ref['expected_text'] = text
            self.save_references()
            self._update_combo_options()
            return True
        return False

    def _remove_reference(self):
        selected = self.tree.selection()
        if not selected:
            return
        item_vals = self.tree.item(selected[0], "values")
        confirm = tb.dialogs.Messagebox.show_question(f"Are you sure you want to delete {item_vals[0]}?", title="Confirm Action", parent=self.mgmt_win)
        if confirm == "Yes":
            self.references = [r for r in self.references if r['name'] != item_vals[0]]
            self.save_references()
            self._populate_reference_tree()
            self._update_combo_options()

    def _update_combo_options(self):
        names = [r['name'] for r in self.references]
        self.ref_combo.configure(values=names)
        if self.ref_var.get() not in names:
            self.ref_var.set("")

    def load_references(self):
        if os.path.exists("references.json"):
            try:
                with open("references.json", "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def save_references(self):
        try:
            with open("references.json", "w") as f:
                json.dump(self.references, f, indent=4)
        except Exception as e:
            print(f"Error saving reference dataset configurations: {e}")

    def on_ref_selected(self, event=None):
        self.selected_reference_name = self.ref_var.get()
        self._update_reference_counters()

    def toggle_modbus(self):
        self.modbus_enabled = not self.modbus_enabled
        status = "ON" if self.modbus_enabled else "OFF"
        style = "success" if self.modbus_enabled else "danger"
        self.modbus_btn.configure(text=f"🔌 Modbus: {status}", bootstyle=style)

    # ─── WINDOW HOOK BINDINGS ───
    def _on_main_window_configure(self, event):
        pass

    def _on_camera_label_configure(self, event):
        if event.width > 10 and event.height > 10:
            self.camera_width = event.width
            self.camera_height = event.height

    def on_mouse_down(self, event):
        self.rect_start = (event.x, event.y)
        self._roi_dragging = True

    def on_mouse_drag(self, event):
        if self._roi_dragging and self.rect_start:
            pass

    def on_mouse_up(self, event):
        self._roi_dragging = False
        if not self.rect_start:
            return
        x0, y0 = self.rect_start
        x1, y1 = event.x, event.y
        rx = min(x0, x1)
        ry = min(y0, y1)
        rw = abs(x1 - x0)
        rh = abs(y1 - y0)
        if rw > 10 and rh > 10:
            selected_ref = next((r for r in self.references if r['name'] == self.selected_reference_name), None)
            if selected_ref:
                scaled_roi = self._preview_to_frame_roi((rx, ry, rw, rh), (self.camera_width, self.camera_height))
                if scaled_roi:
                    selected_ref['roi'] = scaled_roi
                    self.save_references()
                    self.update_result_ui("ROI Configuration Saved Successfully", "success")

    # ─── BACKGROUND PROCESSING EXECUTION ───
    def _start_background_tasks(self):
        def modbus_worker():
            while self.running:
                if self.modbus_enabled:
                    try:
                        if not self.modbus_manager.is_connected():
                            self.modbus_manager.connect()
                        
                        # Process scheduled write actions
                        while not self.modbus_write_queue.empty():
                            task = self.modbus_write_queue.get_nowait()
                            if task["type"] == "write_result":
                                self.modbus_manager.write_result_register(task["value"])
                        
                        # Poll registry for trigger events
                        trigger = self.modbus_manager.read_trigger_register()
                        if trigger == 1:
                            self.modbus_queue.put({"type": "trigger_test"})
                    except Exception as e:
                        print(f"Modbus Thread Communication error profile: {e}")
                time.sleep(self.poll_interval)

        def camera_worker():
            while self.running:
                if self.main_camera_display and self.camera:
                    frame = self.camera.capture_frame()
                    if frame is not None:
                        self.camera_queue.put(frame)
                time.sleep(0.03)

        self.modbus_thread = threading.Thread(target=modbus_worker, daemon=True)
        self.camera_thread = threading.Thread(target=camera_worker, daemon=True)
        self.modbus_thread.start()
        self.camera_thread.start()

    def update_gui_from_queues(self):
        """Processes threading interface queues safely inside Tkinter loop execution context."""
        try:
            while not self.modbus_queue.empty():
                msg = self.modbus_queue.get_nowait()
                if msg["type"] == "trigger_test" and not self._test_in_progress:
                    self._test_in_progress = True
                    self.update_result_ui("Testing operational matrix...", "secondary")
                    self.after(10, lambda: [self._run_selected_reference_test(), setattr(self, '_test_in_progress', False)])
        except queue.Empty:
            pass

        try:
            last_frame = None
            while not self.camera_queue.empty():
                last_frame = self.camera_queue.get_nowait()
            
            if last_frame is not None and self.main_camera_display:
                selected_ref = next((r for r in self.references if r['name'] == self.selected_reference_name), None)
                roi = selected_ref['roi'] if selected_ref else None
                img, _ = self.camera.get_preview_image(
                    target_width=self.camera_width,
                    target_height=self.camera_height,
                    overlay_roi=roi
                )
                if img:
                    self.camera_label.configure(image=img)
                    self.camera_label.image = img
        except queue.Empty:
            pass

        self.after(30, self.update_gui_from_queues)


if __name__ == "__main__":
    if not os.path.exists("references.json"):
        with open("references.json", "w") as f:
            json.dump([], f)
    app = MainApp()
    app.mainloop()