import tkinter as tk
from tkinter import ttk
import ttkbootstrap as tb
from PIL import Image, ImageTk
import camera_module as cam
import theme_module as tm
import modbus_manager as mm
from modbus_manager import RESULT_IDLE, RESULT_OK, RESULT_NOK
import json
import os
import time
import threading # Added import
import queue # Added import

class MainApp(tb.Window):
    def __init__(self):
        super().__init__(themename="superhero")
        self.title("Check Ref - Tunitech")
        width = self.winfo_screenwidth()
        height = self.winfo_screenheight()
        self.geometry(f"{width}x{height}+0+0")
       
        self.running = True
        self.references = self.load_references()
        self.adding_new_ref = False
        self.pending_ref = None
        self.selected_reference_name = None
        self.ok_count = 0
        self.nok_count = 0
        self.ok_counter_var = tk.IntVar(value=0)
        self.nok_counter_var = tk.IntVar(value=0)

        # -- Modbus Client Setup --
        # IMPORTANT: Set the correct IP address for your PLC here
        self.modbus_manager = mm.ModbusManager(host="127.0.0.1") 
        self.last_poll_time = 0
        self.poll_interval = 1  # Poll PLC every 1 second
        self.last_plc_ref = ""
        self._modbus_was_connected = False # Track connection state
        self.modbus_enabled = True  # Flag to enable/disable Modbus communication

        # Virtual Keyboard State
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

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.bind("<Configure>", self._on_main_window_configure) # Bind main window configure event
        self.after(100, lambda: self.state('zoomed')) # Maximize the window after a short delay

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

    def _create_live_preview(self, parent, width=520, height=300, initial_roi=None):
        preview_container = tb.Frame(parent)
        preview_container.pack(padx=10, pady=10, fill="both", expand=True)
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
                self.selected_ref_label.configure(text=f"Reference: {selected_ref['name']}")
            self.save_references()
        else:
            self.ok_counter_var.set(0)
            self.nok_counter_var.set(0)
            if hasattr(self, 'ok_label'):
                self.ok_label.configure(text="OK: 0")
            if hasattr(self, 'nok_label'):
                self.nok_label.configure(text="NOK: 0")
            if hasattr(self, 'selected_ref_label'):
                self.selected_ref_label.configure(text="Reference: None")

    def _clear_ocr_results(self):
        self.update_result_ui("Ready", "info")

    def setup_ui(self):
        # Configure root window grid
        self.grid_rowconfigure(0, weight=0) # Header
        self.grid_rowconfigure(1, weight=1) # Main area (Sidebar + Content)
        self.grid_columnconfigure(0, weight=0) # Sidebar
        self.grid_columnconfigure(1, weight=1) # Main content

        # ─── Header ───
        self.header = tb.Frame(self, bootstyle="light")
        self.header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        self.header.columnconfigure(1, weight=1) # Spacer column

        try:
            logo_img = Image.open("logo.png")
            aspect_ratio = logo_img.width / logo_img.height
            new_height = 50
            new_width = int(new_height * aspect_ratio)
            logo_img = logo_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            self.logo_tk = ImageTk.PhotoImage(logo_img)
            self.logo_label = tb.Label(self.header, image=self.logo_tk)
            self.logo_label.grid(row=0, column=0, padx=15, pady=8, sticky="w")
        except:
            tb.Label(self.header, text="TUNITECH", font=("Helvetica", 22, "bold")).grid(row=0, column=0, padx=15, pady=8, sticky="w")
        try:
            logo2_img = Image.open("logo2.png")
            aspect_ratio2 = logo2_img.width / logo2_img.height
            new_height2 = 50 
            new_width2 = int(new_height2 * aspect_ratio2)
            logo2_img = logo2_img.resize((new_width2, new_height2), Image.Resampling.LANCZOS)
            self.logo2_tk = ImageTk.PhotoImage(logo2_img)
            self.logo2_label = tb.Label(self.header, image=self.logo2_tk)
            # Place the right logo after the Test button
            self.logo2_label.grid(row=0, column=6, padx=15, pady=8, sticky="e")
        except Exception as e:
            print(f"Logo2 not found: {e}")
        # Modbus Toggle Button
        self.modbus_btn = tb.Button(self.header, text="🔌 Modbus: ON", bootstyle="success", command=self.toggle_modbus)
        self.modbus_btn.grid(row=0, column=4, padx=15, pady=10, sticky="e")

        # Test OCR Button beside Modbus
        self.test_btn = tb.Button(self.header, text="Test", bootstyle="success", command=self.test_ocr)
        self.test_btn.grid(row=0, column=5, padx=15, pady=10, sticky="e")
        
        # Reference combobox to select active reference
        self.ref_var = tk.StringVar()
        self.ref_combo = tb.Combobox(self.header, textvariable=self.ref_var,
                                     values=[r['name'] for r in self.references],
                                     state="readonly", width=30)
        self.ref_combo.grid(row=0, column=2, padx=15, pady=10, sticky="e")
        self.ref_combo.bind("<<ComboboxSelected>>", self.on_ref_selected)

        # ─── Sidebar ───
        self.sidebar = tb.Frame(self, bootstyle="dark")
        self.sidebar.grid(row=1, column=0, sticky="nsw", padx=0, pady=0)
        
        # Internal container for sidebar buttons to control padding better
        sidebar_inner = tb.Frame(self.sidebar, bootstyle="dark")
        sidebar_inner.pack(padx=10, pady=10, fill="both", expand=True)

        tb.Button(sidebar_inner, text="⚙ Reference Management", bootstyle="success", command=self.open_reference_management).pack(pady=(10, 5), fill="x")
        self.selected_ref_label = tb.Label(sidebar_inner, text="Reference: None", font=("Helvetica", 14, "bold"), bootstyle="secondary")
        self.selected_ref_label.pack(pady=(10, 5), fill="x")
        self.ok_label = tb.Label(sidebar_inner, text="OK: 0", font=("Helvetica", 18, "bold"), bootstyle="success")
        self.ok_label.pack(pady=(5, 5), fill="x")
        self.nok_label = tb.Label(sidebar_inner, text="NOK: 0", font=("Helvetica", 18, "bold"), bootstyle="danger")
        self.nok_label.pack(pady=(5, 10), fill="x")

        # ─── Main Content ───
        self.main_content = tb.Frame(self)
        self.main_content.grid(row=1, column=1, sticky="nsew", padx=10, pady=10)
       
        # Configure main_content grid to be responsive
        self.main_content.grid_rowconfigure(0, weight=1) # Camera row expands
        self.main_content.grid_rowconfigure(1, weight=0) # Result row
        self.main_content.grid_rowconfigure(2, weight=0) # OCR text row
        self.main_content.grid_columnconfigure(0, weight=1) # Column expands

        self.camera_frame = tb.Labelframe(self.main_content, text="Live Feed")
        self.camera_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.camera_label = tb.Label(self.camera_frame, cursor="arrow")
        self.camera_label.pack(fill="both", expand=True)

        self.result_label = tb.Label(self.main_content, text="Ready", font=("Helvetica", 18, "bold"), bootstyle="info", anchor="center")
        self.result_label.grid(row=1, column=0, sticky="ew", pady=10)
       
        self.camera_label.bind("<Configure>", self._on_camera_label_configure)
        self.camera_label.bind("<Button-1>", self.on_mouse_down)
        self.camera_label.bind("<B1-Motion>", self.on_mouse_drag)
        self.camera_label.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.rect_start = None

    def test_ocr(self):
        ref_name = self.ref_var.get().strip()
        selected_ref = next((r for r in self.references if r['name'] == ref_name), None)
        if not selected_ref:
            tb.dialogs.Messagebox.show_warning("Please select a reference first.", title="Reference Required", parent=self)
            return

        self.camera.set_roi(*selected_ref['roi'])
        self.camera.expected_text = selected_ref['expected_text']
        self.camera.last_detected_text = ""
        self.camera.is_match = False
        self.camera.ocr_done = False

        if not self.camera.current_roi or not self.camera.expected_text:
            tb.dialogs.Messagebox.show_warning("The selected reference has no ROI or expected text.", title="Reference Required", parent=self)
            return

        detected, match = self.camera.perform_ocr_once()
        if match:
            self.update_result_ui("OK", "success")
        else:
            self.update_result_ui("NOK", "danger")
        self._update_reference_counters(match)

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
        kb_width = min(800, int(self.winfo_screenwidth() * 0.6))
        kb_height = 350
        x = (self.winfo_screenwidth() // 2) - (kb_width // 2)
        y = self.winfo_screenheight() - kb_height - 50 # Position at bottom
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

    def _create_child_window(self, title, width, height, parent=None, resizable=(True, True), center=True):
        if parent is None:
            parent = self
        win = tb.Toplevel(parent)
        win.title(title)
        if center:
            screen_width = win.winfo_screenwidth()
            screen_height = win.winfo_screenheight()
            x = (screen_width // 2) - (width // 2)
            y = (screen_height // 2) - (height // 2)
            win.geometry(f"{width}x{height}+{x}+{y}")
        else:
            win.geometry(f"{width}x{height}")
        win.resizable(*resizable)
        win.transient(parent)
        win.attributes("-topmost", True)
        win.lift()
        win.focus_force()
        win.after(200, lambda: win.attributes("-topmost", False))
        return win

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
        main_frame.pack(expand=True, fill="both", padx=10, pady=10)

        keys = [['1','2','3','4','5','6','7','8','9','0'],
                ['q','w','e','r','t','y','u','i','o','p'],
                ['a','s','d','f','g','h','j','k','l'],
                ['z','x','c','v','b','n','m']]

        # Configure grid for main_frame to allow expansion
        for i in range(len(keys) + 1): # +1 for the bottom row of special keys
            main_frame.grid_rowconfigure(i, weight=1)
        for i in range(10): # Assuming max 10 columns for keys
            main_frame.grid_columnconfigure(i, weight=1)

        for r_idx, row_keys in enumerate(keys):
            # Calculate offset for centering shorter rows
            col_offset = (10 - len(row_keys)) // 2 
            for c_idx, key in enumerate(row_keys):
                btn = tb.Button(main_frame, text=key.upper(), command=lambda k=key: self._kb_key(k), takefocus=0)
                btn.grid(row=r_idx, column=c_idx + col_offset, sticky="nsew", padx=2, pady=2)
        
        # Bottom row of special keys
        bottom_row_idx = len(keys)
        
        bottom_frame = tb.Frame(main_frame)
        bottom_frame.grid(row=bottom_row_idx, column=0, columnspan=10, sticky="ew", pady=(8,0))
        
        # Configure bottom_frame columns to be responsive
        bottom_frame.grid_columnconfigure(0, weight=2) # Enter
        bottom_frame.grid_columnconfigure(1, weight=5) # Space
        bottom_frame.grid_columnconfigure(2, weight=2) # Back
        bottom_frame.grid_columnconfigure(3, weight=2) # Clear
        bottom_frame.grid_columnconfigure(4, weight=2) # Close

        tb.Button(bottom_frame, text="Enter", bootstyle="success", command=self._kb_enter, takefocus=0).grid(row=0, column=0, sticky="nsew", padx=5)
        tb.Button(bottom_frame, text="Space", command=lambda: self._kb_key(" "), takefocus=0).grid(row=0, column=1, sticky="nsew", padx=5)
        tb.Button(bottom_frame, text="⌫ Back", bootstyle="warning", command=self._kb_backspace, takefocus=0).grid(row=0, column=2, sticky="nsew", padx=5)
        tb.Button(bottom_frame, text="Clear", bootstyle="danger", command=self._kb_clear, takefocus=0).grid(row=0, column=3, sticky="nsew", padx=5)
        tb.Button(bottom_frame, text="Close", bootstyle="secondary", command=self._close_keyboard, takefocus=0).grid(row=0, column=4, sticky="nsew", padx=5)

    # ─── REFERENCE MANAGEMENT ───
    def open_reference_management(self):
        # Password prompt
        password_win = self._create_child_window("Enter Password", 300, 150, parent=self, resizable=(False, False))

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
        win = self._create_child_window("Reference Management", 720, 520, parent=self)
        win.minsize(680, 460)
        win.bind("<Destroy>", lambda e: self._close_keyboard() if e.widget == win else None)

        # Theme control at top
        theme_frame = tb.Frame(win)
        theme_frame.pack(pady=10)
        tb.Label(theme_frame, text="Theme:", font=("Helvetica", 12)).pack(side="left", padx=5)
        self.theme_mb = tb.Menubutton(theme_frame, text="Themes", bootstyle="primary")
        self.theme_mb.pack(side="left")
        self.theme_menu = tb.Menu(self.theme_mb)
        for theme in tm.get_available_themes():
            self.theme_menu.add_command(label=theme, command=lambda t=theme: self.change_theme(t))
        self.theme_mb["menu"] = self.theme_menu

        # References list
        list_frame = tb.Frame(win)
        list_frame.pack(fill="both", expand=True, padx=15, pady=(10, 5))
        columns = ("name", "expected_text")
        self.ref_tree = tb.Treeview(list_frame, columns=columns, show="headings", bootstyle="info")
        self.ref_tree.heading("name", text="Reference Name")
        self.ref_tree.heading("expected_text", text="Expected OCR Text")
        self.ref_tree.column("name", width=220)
        self.ref_tree.column("expected_text", width=300)
        for ref in self.references:
            self.ref_tree.insert("", tk.END, values=(ref["name"], ref["expected_text"]))
        self.ref_tree.pack(fill="both", expand=True)

        # Store reference to tree for refreshing
        self.management_tree = self.ref_tree

        # Buttons at bottom
        btn_frame = tb.Frame(win)
        btn_frame.pack(pady=(5, 12))
        tb.Button(btn_frame, text="Add", bootstyle="success", command=self._add_reference).pack(side="left", padx=10)
        tb.Button(btn_frame, text="Edit", bootstyle="warning", command=self._edit_reference).pack(side="left", padx=10)
        tb.Button(btn_frame, text="Remove", bootstyle="danger", command=self._remove_reference).pack(side="left", padx=10)
        tb.Button(btn_frame, text="Close", bootstyle="secondary", command=win.destroy).pack(side="left", padx=10)

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
                    self.selected_ref_label.configure(text="Reference: None")
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
        win = self._create_child_window("Edit Reference", 620, 560, parent=self)
        win.bind("<Destroy>", lambda e: [self._close_keyboard() if e.widget == win else None, self._refresh_management_tree(), self._resume_main_camera_display()] if e.widget == win else None)
        self._pause_main_camera_display()

        preview_label = self._create_live_preview(win, width=580, height=300, initial_roi=ref.get('roi'))

        container = tb.Frame(win, padding=15)
        container.pack(fill="both", expand=True)
        container.grid_columnconfigure(0, weight=1)

        tb.Label(container, text="Reference Name:", font=("Helvetica", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(10, 5))
        name_var = tk.StringVar(value=ref.get('name', ''))
        e1 = tb.Entry(container, textvariable=name_var, font=("Helvetica", 14))
        e1.grid(row=1, column=0, sticky="ew", pady=(0, 15))

        tb.Label(container, text="Expected Text:", font=("Helvetica", 12, "bold")).grid(row=2, column=0, sticky="w", pady=(0, 5))
        text_var = tk.StringVar(value=ref.get('expected_text', ''))
        e2 = tb.Entry(container, textvariable=text_var, font=("Helvetica", 14))
        e2.grid(row=3, column=0, sticky="ew", pady=(0, 15))

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

        confirm_btn = tb.Button(container, text="SAVE CHANGES", bootstyle="success-outline", command=confirm)
        confirm_btn.grid(row=4, column=0, sticky="ew", pady=(0, 10))

    # ─── SETTINGS WINDOW ───
    def open_settings(self):
        win = self._create_child_window("Add Reference", 620, 620, parent=self)
        win.bind("<Destroy>", lambda e: [self._close_keyboard() if e.widget == win else None, self._refresh_management_tree(), self._resume_main_camera_display()] if e.widget == win else None)
        self._pause_main_camera_display()

        preview_label = self._create_live_preview(win, width=580, height=320)

        container = tb.Frame(win, padding=15)
        container.pack(fill="both", expand=True)
        container.grid_columnconfigure(0, weight=1)

        tb.Label(container, text="Reference Name:", font=("Helvetica", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(10, 5))
        name_var = tk.StringVar()
        e1 = tb.Entry(container, textvariable=name_var, font=("Helvetica", 14))
        e1.grid(row=1, column=0, sticky="ew", pady=(0, 15))

        tb.Label(container, text="Expected Text:", font=("Helvetica", 12, "bold")).grid(row=2, column=0, sticky="w", pady=(0, 5))
        text_var = tk.StringVar()
        e2 = tb.Entry(container, textvariable=text_var, font=("Helvetica", 14))
        e2.grid(row=3, column=0, sticky="ew", pady=(0, 15))

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

        confirm_btn = tb.Button(container, text="SAVE REFERENCE", bootstyle="success-outline", command=confirm)
        confirm_btn.grid(row=4, column=0, sticky="ew", pady=(0, 10))

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

    def on_ref_selected(self, event):
        ref_name = self.ref_var.get()
        ref_data = next((r for r in self.references if r["name"] == ref_name), None)
        if ref_data:
            self.selected_reference_name = ref_data['name']
            self.camera.set_roi(*ref_data["roi"])
            self.camera.expected_text = ref_data["expected_text"]
            self.update_result_ui(f"Active: {ref_data['name']}", "info")
            if hasattr(self, 'selected_ref_label'):
                self.selected_ref_label.configure(text=f"Reference: {ref_data['name']}")
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
        win = self._create_child_window("Modbus Password", 360, 180, parent=self, resizable=(False, False))
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

        # Check for OCR test result
        # Process Modbus queue
        try:
            while True:
                item = self.modbus_queue.get_nowait()
                if item["type"] == "status":
                    self.update_result_ui(item["text"], item["bootstyle"])
                elif item["type"] == "plc_inputs":
                    self._process_plc_inputs(item["data"])
                elif item["type"] == "error":
                    print(f"Modbus worker error: {item['message']}") # Log or display error
                self.modbus_queue.task_done()
        except queue.Empty:
            pass

        self.after(30, self.update_gui_from_queues)

    def _process_plc_inputs(self, plc_inputs):
        # This logic is adapted from the original poll_plc method
        # Check for reference change from PLC
        if plc_inputs.get('reference') and plc_inputs['reference'] != self.last_plc_ref:
            self.last_plc_ref = plc_inputs['reference']
            ref_data = next((r for r in self.references if r['name'] == self.last_plc_ref), None)
            if ref_data:
                self.ref_var.set(self.last_plc_ref)
                self.on_ref_selected(None) 
            else:
                self.update_result_ui(f"PLC Error: Ref '{self.last_plc_ref}' not found", "danger")
                self.modbus_write_queue.put({"type": "write_result", "value": RESULT_NOK})
                if plc_inputs.get('start_cycle'):
                    self.modbus_write_queue.put({"type": "acknowledge_start"})
        
        # Check for start cycle trigger
        if plc_inputs.get('start_cycle'):
            print("PLC triggered test start.")
            if not self.camera.current_roi or not self.camera.expected_text:
                self.update_result_ui("FAIL: No Active Reference", "danger")
                self.modbus_write_queue.put({"type": "write_result", "value": RESULT_NOK})
            else:
                # Use the latest match status from the camera object
                if self.camera.is_match:
                    self.update_result_ui("OK", "success")
                    self.modbus_write_queue.put({"type": "write_result", "value": RESULT_OK})
                else:
                    self.update_result_ui("NOK", "danger")
                    self.modbus_write_queue.put({"type": "write_result", "value": RESULT_NOK})
            
            # Acknowledge that the cycle has been processed
            self.modbus_write_queue.put({"type": "acknowledge_start"})

    def _on_main_window_configure(self, event):
        # Dynamically scale result_label font based on window height
        if event.widget == self:
            new_height = event.height
            base_size = 18
            scaled_size = max(base_size, int(new_height / 40))
            self.result_label.configure(font=("Helvetica", scaled_size, "bold"))

    def _on_camera_label_configure(self, event):
        # Update camera_label dimensions when it resizes
        if event.width > 0 and event.height > 0:
            self.camera_width = event.width
            self.camera_height = event.height




if __name__ == "__main__":
    if not os.path.exists("references.json"):
        with open("references.json", "w") as f:
            json.dump([], f)
            
    app = MainApp()
    app.mainloop()
