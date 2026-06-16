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
        self.modbus_write_queue = queue.Queue()  # Separate queue for write operations (processed by worker thread)
        self.camera_queue = queue.Queue()
        self.modbus_thread = None
        self.camera_thread = None
        self._start_background_tasks() # New method to start threads
        self.update_gui_from_queues() # Start the GUI update loop

        # Track whether an OCR test is currently running (prevent concurrent tests)
        self._test_in_progress = False

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.bind("<Configure>", self._on_main_window_configure) # Bind main window configure event

    def _screen_size(self):
        return self.winfo_screenwidth(), self.winfo_screenheight()

    def _is_portrait_panel_profile(self):
        """Return True for 7-inch portrait panels (~154mm H x 86mm W, 480x800)."""
        screen_w, screen_h = self._screen_size()
        if screen_w == 480 and screen_h == 800:
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
        if screen_w == 800 and screen_h == 480:
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
        self.running = False # Signal threads to stop
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
        """Updates only the UI result label. Does not send to PLC."""
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
        """Split treeview columns for narrow embedded panels."""
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
        """Load and resize a logo for the header bar."""
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
        """Run OCR test on currently selected reference and write result to PLC reg 16."""
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

        # Center keyboard and make it responsive
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
        """Action buttons sized for narrow embedded panels."""
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
        """Compact form layout for add/edit reference dialogs."""
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
                self.current_next_widget, None,
                getattr(self.current_next_widget, "associated_var", None)
            ))
        else:
            self._close_keyboard()

    def _build_keyboard_layout(self):
        if not self.keyboard_win or not self.keyboard_win.winfo_exists(): return
        for widget in self.keyboard_win.winfo_children(): widget.destroy()
        
        main_frame = tb.Frame(self.keyboard_win)
        hd_portrait = self._is_hd_portrait_panel()
        kb_outer_pad = (4, 4) if self.is_portrait_panel else (5, 5) if hd_portrait else (10, 10)
        main_frame.pack(expand=True, fill="both", padx=kb_outer_pad[0], pady=kb_outer_pad[1])

        keys = [['1','2','3','4','5','6','7','8','9','0'],
                ['q','w','e','r','t','y','u','i','o','p'],
                ['a','s','d','f','g','h','j','k','l'],
                ['z','x','c','v','b','n','m']]

        # Configure grid for main_frame to allow expansion
        compact_profile = self._is_embedded_panel()
        key_font = self._responsive_font(9, True) if compact_profile else ("Helvetica", 11, "bold")
        button_pad_x = 1 if compact_profile else 2
        button_pad_y = 1 if compact_profile else 2
        key_btn_pad = (1, 1) if self.is_portrait_panel else ((2, 2) if hd_portrait else ((2, 1) if compact_profile else (3, 2)))

        for i in range(len(keys) + 1): # +1 for the bottom row of special keys
            main_frame.grid_rowconfigure(i, weight=1)
        for i in range(10): # Assuming max 10 columns for keys
            main_frame.grid_columnconfigure(i, weight=1)

        for r_idx, row_keys in enumerate(keys):
            col_offset = (10 - len(row_keys)) // 2
            for c_idx, key in enumerate(row_keys):
                btn = tb.Button(main_frame, text=key.upper(), command=lambda k=key: self._kb_key(k), takefocus=0,
                                font=key_font, padding=key_btn_pad)
                btn.grid(row=r_idx, column=c_idx + col_offset, sticky="nsew", padx=button_pad_x, pady=button_pad_y)
        
        # Bottom row of special keys
        bottom_row_idx = len(keys)
        
        bottom_frame = tb.Frame(main_frame)
        hd_portrait = self._is_hd_portrait_panel()
        bottom_frame.grid(row=bottom_row_idx, column=0, columnspan=10, sticky="ew", pady=(4 if self.is_portrait_panel else (5 if hd_portrait else 8), 0))
        
        # Configure bottom_frame columns to be responsive
        bottom_frame.grid_columnconfigure(0, weight=2) # Enter
        bottom_frame.grid_columnconfigure(1, weight=5) # Space
        bottom_frame.grid_columnconfigure(2, weight=2) # Back
        bottom_frame.grid_columnconfigure(3, weight=2) # Clear
        bottom_frame.grid_columnconfigure(4, weight=2) # Close

        special_pad = (2, 1) if compact_profile else ((2, 2) if hd_portrait else (4, 2))
        tb.Button(bottom_frame, text="Enter", bootstyle="success", command=self._kb_enter, takefocus=0,
                  font=key_font, padding=special_pad).grid(row=0, column=0, sticky="nsew", padx=2, pady=1)
        tb.Button(bottom_frame, text="Space", command=lambda: self._kb_key(" "), takefocus=0,
                  font=key_font, padding=special_pad).grid(row=0, column=1, sticky="nsew", padx=2, pady=1)
        tb.Button(bottom_frame, text="⌫", bootstyle="warning", command=self._kb_backspace, takefocus=0,
                  font=key_font, padding=special_pad).grid(row=0, column=2, sticky="nsew", padx=2, pady=1)
        tb.Button(bottom_frame, text="Clear", bootstyle="danger", command=self._kb_clear, takefocus=0,
                  font=key_font, padding=special_pad).grid(row=0, column=3, sticky="nsew", padx=2, pady=1)
        tb.Button(bottom_frame, text="Close", bootstyle="secondary", command=self._close_keyboard, takefocus=0,
                  font=key_font, padding=special_pad).grid(row=0, column=4, sticky="nsew", padx=2, pady=1)

    # ─── REFERENCE MANAGEMENT ───
    def open_reference_management(self):
        # Password prompt
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
        win = self._create_child_window("Reference Management", 720, 520, parent=self, fullscreen=self._is_embedded_panel())
        if not self._is_embedded_panel():
            win.minsize(680, 460)
        win.bind("<Destroy>", lambda e: self._close_keyboard() if e.widget == win else None)

        win.grid_rowconfigure(1, weight=1)
        win.grid_columnconfigure(0, weight=1)

        embedded = self._is_embedded_panel()
        outer_pad = 4 if embedded else 10

        theme_frame = tb.Frame(win)
        theme_frame.grid(row=0, column=0, sticky="ew", padx=outer_pad, pady=(outer_pad, 2))
        theme_font = self._responsive_font(10) if embedded else ("Helvetica", 12)
        tb.Label(theme_frame, text="Theme:", font=theme_font).pack(side="left", padx=(0, 4))
        self.theme_mb = tb.Menubutton(theme_frame, text="Themes", bootstyle="primary",
                                      padding=(3, 2) if embedded else (6, 4))
        self.theme_mb.pack(side="left")
        self.theme_menu = tb.Menu(self.theme_mb)
        for theme in tm.get_available_themes():
            self.theme_menu.add_command(label=theme, command=lambda t=theme: self.change_theme(t))
        self.theme_mb["menu"] = self.theme_menu

        list_frame = tb.Frame(win)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=outer_pad, pady=2)
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        col_name_w, col_text_w = self._tree_column_widths()
        columns = ("name", "expected_text")
        self.ref_tree = tb.Treeview(list_frame, columns=columns, show="headings", bootstyle="info")
        self.ref_tree.heading("name", text="Name")
        self.ref_tree.heading("expected_text", text="Expected Text")
        self.ref_tree.column("name", width=col_name_w, minwidth=80, stretch=True)
        self.ref_tree.column("expected_text", width=col_text_w, minwidth=100, stretch=True)
        for ref in self.references:
            self.ref_tree.insert("", tk.END, values=(ref["name"], ref["expected_text"]))
        self.ref_tree.grid(row=0, column=0, sticky="nsew")

        self.management_tree = self.ref_tree

        btn_frame = tb.Frame(win)
        btn_frame.grid(row=2, column=0, sticky="ew", padx=outer_pad, pady=(2, outer_pad))
        self._build_management_buttons(btn_frame, win.destroy)

    def _add_reference(self):
        self._pause_main_camera_display()
        self.open_settings()

    def _edit_reference(self):
        selected = self.management_tree.selection()
        if not selected:
            tb.dialogs.Messagebox.show_warning("Please select a reference to edit.", title="No Selection", parent=self)
            return
        item = self.management_tree.item(selected[0])
        name, expected_text = item['values']
        selected_ref = next((r for r in self.references if r['name'] == name and r['expected_text'] == expected_text), None)
        if not selected_ref:
            tb.dialogs.Messagebox.show_error("Unable to find the selected reference.", title="Error", parent=self)
            return
        self._open_edit_window(selected_ref)

    def _remove_reference(self):
        selected = self.management_tree.selection()
        if not selected:
            tb.dialogs.Messagebox.show_warning("Please select a reference to remove.", title="No Selection", parent=self)
            return
        if tb.dialogs.Messagebox.yesno("Are you sure you want to remove the selected reference?", title="Confirm Remove", parent=self):
            item = self.management_tree.item(selected[0])
            name = item['values'][0]
            self.references = [r for r in self.references if r['name'] != name]
            self.save_references()
            self.update_ref_combo()
            self.management_tree.delete(selected[0])
            if self.selected_reference_name == name:
                self.selected_reference_name = None
                self.camera.clear_roi()
                self.camera.expected_text = ""
                self.ref_var.set("")
                self.update_result_ui("Reference removed", "warning")
                if hasattr(self, 'selected_ref_label'):
                    self.selected_ref_label.configure(text=self._ref_label_text())
                if hasattr(self, 'ok_label'):
                    self.ok_label.configure(text="OK: 0")
                if hasattr(self, 'nok_label'):
                    self.nok_label.configure(text="NOK: 0")

    def _refresh_management_tree(self):
        if hasattr(self, 'management_tree') and self.management_tree.winfo_exists():
            self.management_tree.delete(*self.management_tree.get_children())
            for ref in self.references:
                self.management_tree.insert("", tk.END, values=(ref["name"], ref["expected_text"]))

    def _open_edit_window(self, ref):
        win = self._create_child_window("Edit Reference", 620, 560, parent=self, fullscreen=self._is_embedded_panel())
        win.grid_rowconfigure(0, weight=1)
        win.grid_columnconfigure(0, weight=1)
        win.bind("<Destroy>", lambda e: [self._close_keyboard() if e.widget == win else None, self._refresh_management_tree(), self._resume_main_camera_display()] if e.widget == win else None)
        self._pause_main_camera_display()

        pw, ph = self._preview_dimensions(580, 300)
        preview_label = self._create_live_preview(win, width=pw, height=ph, initial_roi=ref.get('roi'), expand_preview=True)

        name_var = tk.StringVar(value=ref.get('name', ''))
        text_var = tk.StringVar(value=ref.get('expected_text', ''))
        original_name = ref.get('name')

        def confirm():
            new_name = name_var.get().strip()
            new_expected = text_var.get().strip()
            if not new_name or not new_expected:
                tb.dialogs.Messagebox.show_error("All fields are required!", title="Error", parent=win)
                return
            if new_name != original_name and any(r['name'] == new_name for r in self.references):
                tb.dialogs.Messagebox.show_error("Another reference already uses that name.", title="Duplicate Name", parent=win)
                return
            selected_roi = preview_label.local_roi
            if selected_roi is None:
                tb.dialogs.Messagebox.show_warning("Please select an ROI on the live preview.", title="ROI Required", parent=win)
                return
            frame_roi = self._preview_to_frame_roi(selected_roi, preview_label.preview_size)

            ref['name'] = new_name
            ref['expected_text'] = new_expected
            ref['roi'] = frame_roi
            if 'ok_count' not in ref:
                ref['ok_count'] = 0
            if 'nok_count' not in ref:
                ref['nok_count'] = 0

            if self.selected_reference_name == original_name:
                self.selected_reference_name = new_name
                self.ref_var.set(new_name)
                self.camera.expected_text = new_expected

            self.save_references()
            self.update_ref_combo()
            self._refresh_management_tree()
            self._close_keyboard()
            win.destroy()
            self.update_result_ui(f"Reference '{new_name}' updated.", "success")

        self._build_ref_form_window(win, name_var, text_var, "SAVE CHANGES", confirm)

    # ─── SETTINGS WINDOW ───
    def open_settings(self):
        win = self._create_child_window("Add Reference", 620, 620, parent=self, fullscreen=self._is_embedded_panel())
        win.grid_rowconfigure(0, weight=1)
        win.grid_columnconfigure(0, weight=1)
        win.bind("<Destroy>", lambda e: [self._close_keyboard() if e.widget == win else None, self._refresh_management_tree(), self._resume_main_camera_display()] if e.widget == win else None)
        self._pause_main_camera_display()

        pw, ph = self._preview_dimensions(580, 320)
        preview_label = self._create_live_preview(win, width=pw, height=ph, expand_preview=True)

        name_var = tk.StringVar()
        text_var = tk.StringVar()

        def confirm():
            name = name_var.get().strip()
            expected = text_var.get().strip()
            selected_roi = preview_label.local_roi
            if not name or not expected:
                tb.dialogs.Messagebox.show_error("All fields are required!", title="Error", parent=win)
                return
            if not selected_roi:
                tb.dialogs.Messagebox.show_warning("Please select an ROI on the live preview.", title="ROI Required", parent=win)
                return
            frame_roi = self._preview_to_frame_roi(selected_roi, preview_label.preview_size)
            new_ref = {"name": name, "expected_text": expected, "roi": frame_roi, "ok_count": 0, "nok_count": 0}
            self.references.append(new_ref)
            self.save_references()
            self.update_ref_combo()
            self._refresh_management_tree()
            self._close_keyboard()
            win.destroy()
            self.camera.clear_roi()
            self.ref_var.set("")
            self._clear_ocr_results()
            self.update_result_ui(f"Reference '{name}' added.", "success")

        self._build_ref_form_window(win, name_var, text_var, "SAVE REFERENCE", confirm)

    # ─── ARCHIVE & PASSWORD WINDOW ───
    def open_archive(self):
        # Create the archive window
        archive_win = self._create_child_window("Reference Archive", 700, 460, parent=self)
        
        # Header
        lbl = tb.Label(archive_win, text="Saved References & Logs", font=("Helvetica", 16, "bold"), bootstyle="primary")
        lbl.pack(pady=10)

        # Create a table (Treeview) to display the references
        columns = ("name", "expected_text")
        tree = tb.Treeview(archive_win, columns=columns, show="headings", bootstyle="info")
        
        # Define headings
        tree.heading("name", text="Reference Name")
        tree.heading("expected_text", text="Expected OCR Text")
        
        # Set column widths
        tree.column("name", width=200)
        tree.column("expected_text", width=340)

        # Populate the table from your self.references list
        for ref in self.references:
            tree.insert("", tk.END, values=(ref["name"], ref["expected_text"]))

        tree.pack(fill="both", expand=True, padx=20, pady=20)

        # Add a close button
        close_btn = tb.Button(archive_win, text="Close", bootstyle="secondary", command=archive_win.destroy)
        close_btn.pack(pady=10)
    # ─── MOUSE / ROI EVENTS ───
    def on_mouse_up(self, event):
        if not self.rect_start:
            return
        x2, y2 = event.x, event.y

        scale_x = 1 / (self.camera.display_scale_x or 1.0)
        scale_y = 1 / (self.camera.display_scale_y or 1.0)

        x1, y1 = self.rect_start
        ui_x, ui_y = min(x1, x2), min(y1, y2)
        ui_w, ui_h = abs(x2 - x1), abs(y2 - y1)
        rx, ry = int(ui_x * scale_x), int(ui_y * scale_y)
        rw, rh = int(ui_w * scale_x), int(ui_h * scale_y)

        self.camera.temp_roi = None

        if rw < 5 or rh < 5:
            if self.adding_new_ref:
                self.update_result_ui("❌ ROI too small!", "danger")
            self._roi_dragging = False
            self.rect_start = None
            return

        if self.adding_new_ref and self.pending_ref and self._roi_dragging:
            if any(r['name'] == self.pending_ref['name'] for r in self.references):
                self.update_result_ui("❌ Reference name exists!", "danger")
            else:
                self.pending_ref["roi"] = (rx, ry, rw, rh)
                self.references.append(self.pending_ref)
                self.save_references()
                self.update_ref_combo()
                self._refresh_management_tree()

                success_msg = f"✓ Reference '{self.pending_ref['name']}' saved successfully!"
                print(success_msg)
                self.update_result_ui(success_msg, "success")
                self._show_top_message(
                    "Reference Saved",
                    f"Reference '{self.pending_ref['name']}' has been saved with ROI!\nDimensions: {rw}x{rh}px"
                )

                self.camera.clear_roi()
                self.ref_var.set("")
            self.adding_new_ref = False
            self.pending_ref = None
        elif self._roi_dragging:
            self.camera.clear_roi()
            self.camera.set_roi(rx, ry, rw, rh)
            self.update_result_ui("ROI updated manually", "info")

        self._roi_dragging = False
        self.rect_start = None

    def load_references(self):
        if os.path.exists("references.json"):
            with open("references.json", "r") as f:
                references = json.load(f)
            for ref in references:
                if 'ok_count' not in ref:
                    ref['ok_count'] = 0
                if 'nok_count' not in ref:
                    ref['nok_count'] = 0
                if 'roi' not in ref:
                    ref['roi'] = None
            return references
        return []

    def save_references(self):
        try:
            with open("references.json", "w") as f:
                json.dump(self.references, f, indent=4)
            print(f"✓ References saved successfully. Total: {len(self.references)}")
        except Exception as e:
            print(f"✗ Error saving references: {e}")
            tb.dialogs.Messagebox.show_error(f"Failed to save reference: {e}", title="Save Error", parent=self)

    def update_ref_combo(self):
        self.ref_combo['values'] = [r['name'] for r in self.references]

    def _resolve_reference_from_plc(self, received_ref):
        """
        Resolve PLC-provided reference name.
        1) exact match, 2) unique prefix match (to handle partial/slow writes).
        """
        if not received_ref:
            return None

        cleaned = received_ref.strip()
        lowered = cleaned.lower()
        exact = next((r for r in self.references if r["name"].strip().lower() == lowered), None)
        if exact:
            return exact

        prefix_matches = [r for r in self.references if r["name"].strip().lower().startswith(lowered)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
        return None

    def on_ref_selected(self, event):
        ref_name = self.ref_var.get()
        ref_data = next((r for r in self.references if r["name"] == ref_name), None)
        if ref_data:
            self.selected_reference_name = ref_data['name']
            self.camera.set_roi(*ref_data["roi"])
            self.camera.expected_text = ref_data["expected_text"]
            self.update_result_ui(f"Active: {ref_data['name']}", "info")
            if hasattr(self, 'selected_ref_label'):
                self.selected_ref_label.configure(text=self._ref_label_text(ref_data['name']))
            if hasattr(self, 'ok_label'):
                self.ok_label.configure(text=f"OK: {ref_data.get('ok_count', 0)}")
            if hasattr(self, 'nok_label'):
                self.nok_label.configure(text=f"NOK: {ref_data.get('nok_count', 0)}")
            # Queue Modbus write to worker thread (never blocks main thread)
            self.modbus_write_queue.put({"type": "write_result", "value": RESULT_IDLE})

    def on_mouse_down(self, event):
        self.rect_start = (event.x, event.y)
        self._roi_dragging = True
        self.camera.temp_roi = None

    def on_mouse_drag(self, event):
        if self.rect_start:
            self._roi_dragging = True
            if self.camera.current_roi and self.camera.temp_roi is None:
                self.camera.clear_roi()
            
            scale_x = 1 / (self.camera.display_scale_x or 1.0)
            scale_y = 1 / (self.camera.display_scale_y or 1.0)

            x1, y1 = self.rect_start
            x2, y2 = event.x, event.y
            ui_x, ui_y = min(x1, x2), min(y1, y2)
            ui_w, ui_h = abs(x2 - x1), abs(y2 - y1)
            
            frame_x = int(ui_x * scale_x)
            frame_y = int(ui_y * scale_y)
            frame_w = int(ui_w * scale_x)
            frame_h = int(ui_h * scale_y)

            self.camera.set_roi_temp(frame_x, frame_y, frame_w, frame_h)

    def change_theme(self, name): tm.set_theme(self, name)

    def toggle_modbus(self):
        self._prompt_modbus_password()

    def _toggle_modbus_state(self):
        """Toggle Modbus communication on/off once the password is validated."""
        self.modbus_enabled = not self.modbus_enabled
        if self.modbus_enabled:
            self.modbus_btn.configure(text="🔌 Modbus: ON", bootstyle="success")
            self.update_result_ui("Modbus reconnecting...", "info")
        else:
            self.modbus_btn.configure(text="🔌 Modbus: OFF", bootstyle="danger")
            self.modbus_manager.disconnect()
            self.update_result_ui("Modbus disconnected", "warning")

    def _prompt_modbus_password(self):
        mb_w, mb_h = (340, 170) if self.is_portrait_panel else (360, 180)
        win = self._create_child_window("Modbus Password", mb_w, mb_h, parent=self, resizable=(False, False))
        tb.Label(win, text="Enter password to change Modbus state:", font=("Helvetica", 11), wraplength=320, justify="center").pack(pady=(15, 5), padx=10)

        password_var = tk.StringVar()
        password_entry = tb.Entry(win, textvariable=password_var, show="*", font=("Helvetica", 14))
        password_entry.pack(pady=5, padx=20, fill="x")
        password_entry.focus_set()
        win.bind("<Destroy>", lambda e: self._close_keyboard() if e.widget == win else None)
        win.protocol("WM_DELETE_WINDOW", lambda: [self._close_keyboard(), win.destroy()])

        def check_password(event=None):
            if password_var.get().strip().upper() == "TUNITECH":
                self._close_keyboard()
                win.destroy()
                self._toggle_modbus_state()
                self._open_modbus_settings_window()
            else:
                tb.dialogs.Messagebox.show_error("Incorrect password, please try again.", title="Error", parent=win)
                password_var.set("")
                password_entry.focus_set()

        password_entry.bind("<Return>", check_password)

        button_frame = tb.Frame(win)
        button_frame.pack(pady=(8, 12), padx=20, fill="x")
        tb.Button(button_frame, text="Enter", bootstyle="success", command=check_password).pack(side="left", expand=True, fill="x", padx=(0, 5))
        tb.Button(button_frame, text="Cancel", bootstyle="secondary", command=lambda: [self._close_keyboard(), win.destroy()]).pack(side="left", expand=True, fill="x", padx=(5, 0))

        win.after(100, lambda: self.show_virtual_keyboard(password_entry, None, password_var))

    def _open_modbus_settings_window(self):
        win = self._create_child_window("Modbus Settings", 420, 220, parent=self)
        tb.Label(win, text="Modbus is now:", font=("Helvetica", 12, "bold")).pack(pady=(20, 8))
        status_text = "ON" if self.modbus_enabled else "OFF"
        status_bootstyle = "success" if self.modbus_enabled else "danger"
        tb.Label(win, text=status_text, font=("Helvetica", 24, "bold"), bootstyle=status_bootstyle).pack(pady=(0, 15))
        tb.Label(win, text="You can close this window to continue.", font=("Helvetica", 11), wraplength=360, justify="center").pack(pady=(0, 15), padx=10)
        tb.Button(win, text="Close", bootstyle="primary", command=win.destroy).pack(pady=(0, 10))

    def clear_zone(self):
        self.camera.clear_roi()
        self.ref_var.set("")
        self.update_result_ui("Zone Cleared", "warning")
        # Queue Modbus write to worker thread (never blocks main thread)
        self.modbus_write_queue.put({"type": "write_result", "value": RESULT_IDLE})

    def _start_background_tasks(self):
        """Starts the Modbus and Camera worker threads."""
        self.modbus_thread = threading.Thread(target=self._modbus_worker, daemon=True)
        self.camera_thread = threading.Thread(target=self._camera_worker, daemon=True)
        self.modbus_thread.start()
        self.camera_thread.start()

    def _modbus_worker(self):
        """Worker thread for Modbus communication."""
        while self.running:
            try:
                # Process any pending write operations first (highest priority)
                try:
                    while True:
                        write_item = self.modbus_write_queue.get_nowait()
                        if write_item["type"] == "write_result":
                            if self.modbus_enabled and self.modbus_manager.connected:
                                self.modbus_manager.write_result(write_item["value"])
                        elif write_item["type"] == "acknowledge_start":
                            if self.modbus_enabled and self.modbus_manager.connected:
                                self.modbus_manager.acknowledge_start()
                except queue.Empty:
                    pass
                
                # Check if Modbus is disabled
                if not self.modbus_enabled:
                    time.sleep(0.5)
                    continue
                
                # Attempt to connect if not already connected
                if not self.modbus_manager.connected:
                    self.modbus_manager.connect()
                    if not self.modbus_manager.connected:
                        self.modbus_queue.put({"type": "status", "text": "PLC Disconnected", "bootstyle": "secondary"})
                        self._modbus_was_connected = False
                        time.sleep(self.poll_interval)
                        continue # Try connecting again after a delay

                # If connected, poll for PLC inputs
                current_time = time.time()
                if (current_time - self.last_poll_time) > self.poll_interval:
                    self.last_poll_time = current_time
                    plc_inputs = self.modbus_manager.read_plc_inputs()

                    if plc_inputs is None:
                        # Disconnection detected or read error
                        if self.modbus_manager.connected:
                            self.modbus_manager.disconnect()
                        self.modbus_queue.put({"type": "status", "text": "PLC Disconnected", "bootstyle": "secondary"})
                        self._modbus_was_connected = False
                        continue # Will attempt to reconnect in next loop iteration

                    # Only report successful connection once after a disconnection
                    if not self._modbus_was_connected and self.modbus_manager.connected:
                        self.modbus_queue.put({"type": "status", "text": "PLC Connected", "bootstyle": "success"})
                        self._modbus_was_connected = True
                    
                    self.modbus_queue.put({"type": "plc_inputs", "data": plc_inputs})
                    
                time.sleep(0.1) # Small delay to prevent busy-waiting
            except Exception as e:
                self.modbus_queue.put({"type": "error", "message": f"Modbus worker error: {e}"})
                self._modbus_was_connected = False # Assume disconnected on error
                time.sleep(1) # Wait a bit before retrying after an error

    def _camera_worker(self):
        """Worker thread for camera feed processing."""
        # Initial camera start attempt
        camera_started = False
        while not camera_started and self.running:
            self.camera_queue.put({"type": "status", "text": "Starting camera...", "bootstyle": "info"})
            camera_started = self.camera.start_camera(0)
            if not camera_started:
                self.camera_queue.put({"type": "status", "text": "Camera failed to start, retrying...", "bootstyle": "danger"})
                time.sleep(3) # Wait before retrying camera
        frame_count = 0
        while self.running:
            img_tk, is_match = self.camera.get_frame(
                self.camera_width,
                self.camera_height,
                run_ocr=False
            )
            
            if img_tk:
                # Prevent queue buildup by dropping old frames if the GUI is lagging
                try:
                    while self.camera_queue.qsize() > 2:
                        self.camera_queue.get_nowait()
                    self.camera_queue.put({"type": "frame", "img_tk": img_tk, "is_match": is_match})
                except queue.Empty:
                    pass
            
            frame_count += 1
            time.sleep(0.03) # Lower CPU load while keeping a smooth frame rate

    def update_gui_from_queues(self):
        if not self.running: return

        # Process camera queue
        latest_frame = None
        try:
            while True:
                item = self.camera_queue.get_nowait()
                if item["type"] == "frame":
                    if self.main_camera_display:
                        latest_frame = item["img_tk"]
                        self.camera_label.image = item["img_tk"]
                elif item["type"] == "status":
                    self.update_result_ui(item["text"], item["bootstyle"])
                elif item["type"] == "error":
                    print(f"Camera worker error: {item['message']}") # Log or display error
                self.camera_queue.task_done()
        except queue.Empty:
            pass

        if latest_frame is not None and self.main_camera_display:
            self.camera_label.configure(image=latest_frame)

        # Process Modbus queue
        try:
            while True:
                item = self.modbus_queue.get_nowait()
                if item["type"] == "status":
                    self.update_result_ui(item["text"], item["bootstyle"])
                elif item["type"] == "plc_test_result":
                    match = item.get("data", {}).get("match")
                    if match:
                        self.update_result_ui("OK", "success")
                    else:
                        self.update_result_ui("NOK", "danger")
                    # Update counters for selected ref
                    self._update_reference_counters(match)
                elif item["type"] == "plc_inputs":
                    self._process_plc_inputs(item["data"])
                elif item["type"] == "error":
                    print(f"Modbus worker error: {item['message']}") # Log or display error
                self.modbus_queue.task_done()
        except queue.Empty:
            pass

        self.after(30, self.update_gui_from_queues)

    def _process_plc_inputs(self, plc_inputs):
        if not plc_inputs:
            return

        received_ref = plc_inputs.get('reference', '').strip()
        start_test = plc_inputs.get('start_test')
        resolved_ref = self._resolve_reference_from_plc(received_ref) if received_ref else None

        # Show raw PLC value only when it cannot be resolved yet.
        if received_ref and not resolved_ref:
            self.ref_var.set(received_ref)

        # Update combobox selection when a valid/uniquely-resolved ref arrives.
        # Re-apply if current selected reference does not match, even when same PLC ref repeats.
        if resolved_ref and (
            resolved_ref['name'] != self.last_plc_ref
            or self.selected_reference_name != resolved_ref['name']
        ):
            self.last_plc_ref = resolved_ref['name']
            self.ref_var.set(resolved_ref['name'])
            self.on_ref_selected(None)
            self.update_result_ui(f"PLC selected: {resolved_ref['name']}", "info")

        # PLC start-test bit triggers same OCR flow as GUI Test button.
        if start_test:
            # Start the OCR test in a background thread to avoid blocking the GUI.
            self._start_test_thread()
            # Acknowledge reg 15 back to 0 so simulator start button can be pressed again.
            self.modbus_write_queue.put({"type": "acknowledge_start"})

    def _on_main_window_configure(self, event):
        if event.widget == self:
            if self.is_portrait_panel:
                scaled_size = max(10, min(14, int(event.height / 58)))
            elif self._is_landscape_panel_profile():
                scaled_size = max(11, min(15, int(event.height / 32)))
            else:
                scaled_size = max(14, int(event.height / 40))
            self.result_label.configure(font=("Helvetica", scaled_size, "bold"))

    def _on_camera_label_configure(self, event):
        if event.width > 0 and event.height > 0:
            self.camera_width = event.width
            self.camera_height = event.height

    def _start_test_thread(self):
        """Start OCR test in background thread and deliver result back to GUI via queue."""
        if self._test_in_progress:
            return

        # Validate selection on main thread before starting
        ref_name = self.ref_var.get().strip()
        selected_ref = next((r for r in self.references if r['name'] == ref_name), None)
        if not selected_ref:
            self.update_result_ui("FAIL: No Active Reference", "danger")
            return

        self._test_in_progress = True
        self.update_result_ui("Running...", "secondary")

        def worker():
            try:
                # Ensure camera is configured for this reference
                self.camera.set_roi(*selected_ref['roi'])
                self.camera.expected_text = selected_ref['expected_text']
                detected, match = self.camera.perform_ocr_once()

                # Send result back to main thread via queue for safe UI updates
                self.modbus_queue.put({"type": "plc_test_result", "data": {"match": match}})

                # Queue write to PLC result register
                if match:
                    self.modbus_write_queue.put({"type": "write_result", "value": RESULT_OK})
                else:
                    self.modbus_write_queue.put({"type": "write_result", "value": RESULT_NOK})
            except Exception as e:
                self.modbus_queue.put({"type": "status", "text": f"Test error: {e}", "bootstyle": "danger"})
            finally:
                self._test_in_progress = False

        threading.Thread(target=worker, daemon=True).start()




if __name__ == "__main__":
    if not os.path.exists("references.json"):
        with open("references.json", "w") as f:
            json.dump([], f)
            
    app = MainApp()
    app.mainloop()