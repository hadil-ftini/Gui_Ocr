import tkinter as tk
from tkinter import ttk
import ttkbootstrap as tb
from PIL import Image, ImageTk
import camera_module as cam
import theme_module as tm
import json
import os


class MainApp(tb.Window):
    def __init__(self):
        super().__init__(themename="superhero")
        self.title("Check Ref")
        self.geometry("1000x750")

        self.running = True

        # Data
        self.references = self.load_references()
        self.adding_new_ref = False
        self.editing_ref = None
        self.pending_ref = None

        # Header
        self.header_frame = tb.Frame(self, bootstyle="light")
        self.header_frame.pack(side="top", fill="x", padx=10, pady=5)

        # Logo
        try:
            logo_img = Image.open("logo.png")
            aspect_ratio = logo_img.width / logo_img.height
            new_height = 50
            new_width = int(new_height * aspect_ratio)
            logo_img = logo_img.resize((new_width, new_height))
            self.logo_tk = ImageTk.PhotoImage(logo_img)
            self.logo_label = tb.Label(self.header_frame, image=self.logo_tk, bootstyle="inverse-light")
            self.logo_label.pack(side="left", padx=10)
        except Exception:
            self.logo_label = tb.Label(self.header_frame, text="TUNITECH", font=("Helvetica", 20, "bold"))
            self.logo_label.pack(side="left", padx=10)

        # Theme selector
        self.theme_mb = tb.Menubutton(self.header_frame, text="Themes", bootstyle="primary")
        self.theme_mb.pack(side="right", padx=10)
        self.theme_menu = tb.Menu(self.theme_mb)
        for theme in tm.get_available_themes():
            self.theme_menu.add_command(label=theme, command=lambda t=theme: self.change_theme(t))
        self.theme_mb["menu"] = self.theme_menu

        # Reference dropdown
        self.ref_var = tk.StringVar()
        self.ref_combo = tb.Combobox(
            self.header_frame,
            textvariable=self.ref_var,
            values=[ref['name'] for ref in self.references],
            state="readonly",
            width=25
        )
        self.ref_combo.pack(side="right", padx=10)

        # Sidebar
        self.sidebar = tb.Frame(self, bootstyle="dark")
        self.sidebar.pack(side="left", fill="y", padx=8, pady=10)

        self.settings_btn = tb.Button(self.sidebar, text="⚙ Add Reference",
                                      bootstyle="success", width=20,
                                      command=self.open_settings)
        self.settings_btn.pack(pady=12, padx=10)

        self.archive_btn = tb.Button(self.sidebar, text="📁 Archive",
                                     bootstyle="primary", width=20,
                                     command=self.open_archive)
        self.archive_btn.pack(pady=8, padx=10)

        # Main Content
        self.main_content = tb.Frame(self)
        self.main_content.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        self.result_label = tb.Label(self.main_content,
                                     text="Draw ROI to check reference",
                                     font=("Helvetica", 16, "bold"),
                                     bootstyle="info")
        self.result_label.pack(side="bottom", pady=15)

        self.controls_frame = tb.Frame(self.main_content)
        self.controls_frame.pack(side="bottom", fill="x", pady=10)
        self.stop_btn = tb.Button(self.controls_frame, text="Stop Camera", bootstyle="danger", command=self.stop_all)
        self.stop_btn.pack(side="left", padx=10)
        self.clear_zone_btn = tb.Button(self.controls_frame, text="Clear Zone", bootstyle="warning", command=self.clear_zone)
        self.clear_zone_btn.pack(side="left", padx=10)

        self.camera_frame = tb.Labelframe(self.main_content, text="Camera Feed")
        self.camera_frame.pack(side="top", pady=10, padx=10, fill="both", expand=True)
        self.camera_label = tb.Label(self.camera_frame)
        self.camera_label.pack(expand=True, fill="both")

        # Mouse bindings for ROI
        self.camera_label.bind("<Button-1>", self.on_mouse_down)
        self.camera_label.bind("<B1-Motion>", self.on_mouse_drag)
        self.camera_label.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.rect_start = None

        # Camera
        self.camera = cam.CameraApp()
        self.start_camera()
        self.update_camera()

        self.ref_combo.bind("<<ComboboxSelected>>", self.on_ref_selected)

        # Virtual keyboard window
        self.keyboard_win = None
        self.current_kb_entry = None
        self._closing_keyboard = False  # Flag to prevent immediate reopening

    # ────────────────────────────────────────────────
    #               VIRTUAL KEYBOARD
    # ────────────────────────────────────────────────
    def show_virtual_keyboard(self, entry, next_widget=None):
        """
        Create and show the virtual keyboard when an Entry (or reference field)
        is focused or clicked. Reuses the same window if it already exists.
        """
        # Don't open keyboard if we're in the process of closing it
        if self._closing_keyboard:
            return
            
        if self.keyboard_win and self.keyboard_win.winfo_exists():
            # If keyboard window exists but was hidden, show it again
            self.keyboard_win.deiconify()
            self.keyboard_win.lift()
            self.keyboard_win.focus_force()
        else:
            # Create new keyboard window
            self.keyboard_win = tb.Toplevel(self)
            self.keyboard_win.title("Virtual Keyboard")
            self.keyboard_win.geometry("630x250+300+300")
            self.keyboard_win.resizable(False, False)
            # When user closes the window (X), use the same close logic as OK
            self.keyboard_win.protocol("WM_DELETE_WINDOW", self._close_keyboard)

        for widget in self.keyboard_win.winfo_children():
            widget.destroy()

        self.current_kb_entry = entry

        kb_frame = tb.Frame(self.keyboard_win, bootstyle="dark")
        kb_frame.pack(pady=12, padx=10, fill="both", expand=True)

        layout = [
            "1234567890",
            "QWERTYUIOP",
            "ASDFGHJKL",
            "ZXCVBNM"
        ]

        for row_chars in layout:
            row = tb.Frame(kb_frame)
            row.pack(pady=4, fill="x")
            for char in row_chars:
                tb.Button(
                    row, text=char, width=5, bootstyle="info",
                    command=lambda c=char: entry.insert(tk.END, c)
                ).pack(side="left", padx=3)

        bottom = tb.Frame(kb_frame)
        bottom.pack(pady=8, fill="x")

        tb.Button(
            bottom, text="⌫", width=8, bootstyle="warning",
            command=lambda: entry.delete(len(entry.get())-1, tk.END) if entry.get() else None
        ).pack(side="left", padx=6)

        tb.Button(
            bottom, text="Space", width=24, bootstyle="secondary",
            command=lambda: entry.insert(tk.END, " ")
        ).pack(side="left", padx=6, expand=True, fill="x")

        if next_widget:
            tb.Button(
                bottom, text="Next →", width=10, bootstyle="success",
                command=lambda: self._move_to_next(entry, next_widget)
            ).pack(side="right", padx=6)
        else:
            tb.Button(
                bottom, text="OK", width=10, bootstyle="success",
                command=lambda: self._close_keyboard()
            ).pack(side="right", padx=6)

        entry.unbind("<Return>")
        if next_widget:
            entry.bind("<Return>", lambda e: self._move_to_next(entry, next_widget))
        else:
            entry.bind("<Return>", lambda e: self._close_keyboard())

    def _close_keyboard(self):
        """Close/destroy the virtual keyboard window (used by OK button)."""
        self._closing_keyboard = True  # Prevent immediate reopening during close
        try:
            if self.keyboard_win:
                # Only destroy the keyboard window itself – do NOT quit the whole app
                self.keyboard_win.destroy()
        except Exception:
            pass
        # Clear references
        self.keyboard_win = None
        self.current_kb_entry = None
        # Allow keyboard to be opened again shortly after
        self.after(150, lambda: setattr(self, "_closing_keyboard", False))

    def hide_keyboard(self):
        """Backward-compatible alias kept for existing calls."""
        self._close_keyboard()

    def _move_to_next(self, current_entry, next_widget):
        # Move focus first
        if next_widget:
            next_widget.focus_set()
            if isinstance(next_widget, (tb.Entry, tk.Entry)):
                next_widget.select_range(0, tk.END)
                next_widget.icursor(tk.END)
            # Force focus (helps in some environments)
            self.after(50, lambda: next_widget.focus_force())
            # Explicitly show keyboard for the next field
            self.after(100, lambda: self.show_virtual_keyboard(next_widget, None))
        else:
            # No next field → close keyboard (OK behavior)
            self._close_keyboard()

    # ────────────────────────────────────────────────
    #                   REFERENCES
    # ────────────────────────────────────────────────
    def load_references(self):
        if os.path.exists("references.json"):
            try:
                with open("references.json", "r") as f:
                    return json.load(f)
            except:
                return []
        return []

    def save_references(self):
        with open("references.json", "w") as f:
            json.dump(self.references, f, indent=4)

    def update_ref_combo(self):
        self.ref_combo['values'] = [ref['name'] for ref in self.references]

    def open_settings(self):
        win = tb.Toplevel(self)
        win.title("Add New Reference")
        win.geometry("520x340")
        win.resizable(False, False)

        tb.Label(win, text="Reference Name:", font=("Helvetica", 11)).pack(pady=(20, 2))
        name_entry = tb.Entry(win, width=50, font=("Helvetica", 12))
        name_entry.pack(pady=4)

        tb.Label(win, text="Expected Text:", font=("Helvetica", 11)).pack(pady=(20, 2))
        text_entry = tb.Entry(win, width=50, font=("Helvetica", 12))
        text_entry.pack(pady=4)

        name_entry.bind("<FocusIn>", lambda e: self.show_virtual_keyboard(name_entry, text_entry))
        text_entry.bind("<FocusIn>", lambda e: self.show_virtual_keyboard(text_entry, None))

        name_entry.focus()

        def next_step():
            name = name_entry.get().strip()
            expected = text_entry.get().strip()
            if not name or not expected:
                tb.dialogs.Messagebox.show_error("Please fill both fields", title="Error")
                return
            win.destroy()
            self.pending_ref = {'name': name, 'expected_text': expected, 'roi': None}
            self.adding_new_ref = True
            self.result_label.configure(text=f"Draw ROI for: {name}", bootstyle="warning")
            self.hide_keyboard()

        tb.Button(win, text="Draw ROI on Camera", bootstyle="primary",
                  command=next_step, width=30).pack(pady=25)

    # ────────────────────────────────────────────────
    #                   ARCHIVE (unchanged)
    # ────────────────────────────────────────────────
    def open_archive(self):
        pw_win = tb.Toplevel(self)
        pw_win.title("Password Required")
        pw_win.geometry("350x180")

        tb.Label(pw_win, text="Enter Password:", font=("Helvetica", 11)).pack(pady=20)
        pw_entry = tb.Entry(pw_win, show="*", width=30, font=("Helvetica", 11))
        pw_entry.pack(pady=5)
        pw_entry.focus()

        pw_entry.bind("<FocusIn>", lambda e: self.show_virtual_keyboard(pw_entry, None))

        def verify():
            if pw_entry.get() == "tunitech":
                pw_win.destroy()
                self.show_archive_window()
                self.hide_keyboard()
            else:
                tb.dialogs.Messagebox.show_error("Incorrect password!", title="Access Denied")

        tb.Button(pw_win, text="login", bootstyle="danger", command=verify).pack(pady=15)

    def show_archive_window(self):
        win = tb.Toplevel(self)
        win.title("Reference Archive")
        win.geometry("800x500")

        columns = ("Name", "Expected Text", "ROI")
        tree = ttk.Treeview(win, columns=columns, show="headings", height=15)
        for col, width in zip(columns, [180, 380, 180]):
            tree.heading(col, text=col)
            tree.column(col, width=width)
        tree.pack(fill="both", expand=True, padx=15, pady=15)

        for ref in self.references:
            roi_str = f"{ref['roi'][0]},{ref['roi'][1]},{ref['roi'][2]},{ref['roi'][3]}" if ref.get('roi') else "Not set"
            tree.insert("", "end", values=(ref['name'], ref['expected_text'], roi_str))

        btn_frame = tb.Frame(win)
        btn_frame.pack(pady=10)

        tb.Button(btn_frame, text="Delete Selected", bootstyle="danger",
                  command=lambda: self.delete_ref(tree)).pack(side="left", padx=10)
        tb.Button(btn_frame, text="Edit Selected", bootstyle="warning",
                  command=lambda: self.edit_ref(tree)).pack(side="left", padx=10)

    def delete_ref(self, tree):
        selected = tree.selection()
        if not selected:
            return
        name = tree.item(selected[0])['values'][0]
        self.references = [r for r in self.references if r['name'] != name]
        self.save_references()
        self.update_ref_combo()
        tree.delete(selected[0])

    def edit_ref(self, tree):
        selected = tree.selection()
        if not selected:
            return
        name = tree.item(selected[0])['values'][0]
        for ref in self.references:
            if ref['name'] == name:
                self.start_edit(ref)
                break

    def start_edit(self, ref):
        self.editing_ref = ref
        self.result_label.configure(text=f"Redraw ROI for: {ref['name']} (or just edit info)", bootstyle="warning")

    def on_mouse_down(self, event):
        self.rect_start = (event.x, event.y)

    def on_mouse_drag(self, event):
        if self.rect_start:
            x1, y1 = self.rect_start
            x2, y2 = event.x, event.y
            if abs(x2 - x1) > 10 and abs(y2 - y1) > 10:
                self.camera.set_roi_temp(x1, y1, x2 - x1, y2 - y1)

    def on_mouse_up(self, event):
        if not self.rect_start:
            return

        x1, y1 = self.rect_start
        x2, y2 = event.x, event.y
        x_min, x_max = min(x1, x2), max(x1, x2)
        y_min, y_max = min(y1, y2), max(y1, y2)
        w = x_max - x_min
        h = y_max - y_min

        if w <= 30 or h <= 30:
            self.rect_start = None
            self.result_label.configure(
                text="Selection too small — please try again",
                bootstyle="warning"
            )
            return

        scale = self.camera.display_scale
        x = int(x_min / scale)
        y = int(y_min / scale)
        w = int(w / scale)
        h = int(h / scale)

        success_message_shown = False

        if self.adding_new_ref and self.pending_ref:
            self.pending_ref['roi'] = (x, y, w, h)
            self.references.append(self.pending_ref)
            self.save_references()
            self.update_ref_combo()

            ref_name = self.pending_ref['name']

            self.result_label.configure(
                text=f"✓ Reference '{ref_name}' saved successfully!",
                bootstyle="success"
            )

            self.after(400, lambda n=ref_name: tb.dialogs.Messagebox.show_info(
                message=f"Reference **{n}** created successfully!\nROI has been saved.",
                title="Reference Saved",
                bootstyle="success",
                parent=self
            ))
            success_message_shown = True

            self.adding_new_ref = False
            self.pending_ref = None
            # Hide ROI overlay after saving; it will re-appear when this
            # reference is selected from the dropdown.
            self.camera.clear_roi()

        elif self.editing_ref:
            ref_name = self.editing_ref['name']
            self.editing_ref['roi'] = (x, y, w, h)
            self.save_references()
            self.update_ref_combo()

            self.result_label.configure(
                text=f"✓ ROI updated for '{ref_name}'",
                bootstyle="success"
            )

            self.after(400, lambda n=ref_name: tb.dialogs.Messagebox.show_info(
                message=f"Region of Interest for **{n}** has been updated.",
                title="ROI Updated",
                bootstyle="success",
                parent=self
            ))
            success_message_shown = True

            self.editing_ref = None
            # Also hide ROI overlay after updating; it will show again
            # when the reference is selected.
            self.camera.clear_roi()

        else:
            self.camera.set_roi(x, y, w, h)
            result = self.camera.check_reference()
            self.result_label.configure(text=result, bootstyle="info")

        self.rect_start = None

        if success_message_shown:
            self.after(2800, lambda: self.result_label.configure(
                text="Select a reference or add a new one",
                bootstyle="info"
            ))

    def on_ref_selected(self, event=None):
        name = self.ref_var.get()
        for ref in self.references:
            if ref['name'] == name:
                self.camera.set_roi(*ref['roi'])
                if hasattr(self.camera, 'set_expected_text'):
                    self.camera.set_expected_text(ref['expected_text'])
                self.result_label.configure(text=f"Loaded: {name} | Draw new ROI or click Check", bootstyle="info")
                break

    def start_camera(self):
        self.camera.start_camera(camera_index=1)
        self.camera_label.configure(text="")

    def stop_all(self):
        self.running = False
        self.camera.stop_camera()
        self.camera_label.configure(image='', text="Camera Stopped")

    def clear_zone(self):
        self.camera.clear_roi()
        self.result_label.configure(text="Zone cleared — draw new ROI if needed", bootstyle="warning")

    def update_camera(self):
        if not self.running:
            return
        if self.camera.is_running:
            frame = self.camera.get_frame()
            if frame:
                self.camera_label.configure(image=frame)
                self.camera_label.image = frame
        self.after(30, self.update_camera)

    def change_theme(self, theme_name):
        tm.set_theme(self, theme_name)

    def destroy(self):
        self.running = False
        self.camera.stop_camera()
        if self.keyboard_win and self.keyboard_win.winfo_exists():
            self.keyboard_win.destroy()
        super().destroy()


if __name__ == "__main__":
    app = MainApp()
    app.mainloop()