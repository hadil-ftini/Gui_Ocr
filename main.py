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
        # self.attributes('-fullscreen', True)  # uncomment only if needed

        self.running = True

        # Data
        self.references = self.load_references()
        self.adding_new_ref = False
        self.editing_ref = None
        self.pending_ref = None

        # ─── Header ───
        self.header_frame = tb.Frame(self, bootstyle="light")
        self.header_frame.pack(side="top", fill="x", padx=10, pady=5)

        # Logo
        try:
            logo_img = Image.open("logo.png")
            aspect_ratio = logo_img.width / logo_img.height
            new_height = 50
            new_width = int(new_height * aspect_ratio)
            logo_img = logo_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
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

        # ─── Sidebar ───
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

        # ─── Main Content ───
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

        # ─── Camera ───
        self.camera = cam.CameraApp()
        self.start_camera()
        self.update_camera()

        self.ref_combo.bind("<<ComboboxSelected>>", self.on_ref_selected)

        # ─── Virtual Keyboard support ───
        self.keyboard_win = None
        self.current_kb_entry = None
        self.current_kb_var = None
        self._closing_keyboard = False

        # Global physical keyboard fallback (very useful on Raspberry Pi)
        self.bind_all("<Key>", self._global_key_fallback, add="+")

    def _global_key_fallback(self, event):
        """Catch physical keyboard input when normal focus fails"""
        if not self.current_kb_entry or not self.current_kb_entry.winfo_exists():
            return

        char = event.char
        keysym = event.keysym

        if char and char.isprintable():
            self._kb_insert_char(char)
        elif keysym == "BackSpace":
            self._kb_backspace()
        elif keysym in ("Return", "KP_Enter"):
            self._close_keyboard()
        elif keysym == "space":
            self._kb_space()

    # ────────────────────────────────────────────────
    #               VIRTUAL KEYBOARD
    # ────────────────────────────────────────────────
    def show_virtual_keyboard(self, entry, next_widget=None, kb_var=None):
        if self._closing_keyboard:
            return

        if self.keyboard_win and self.keyboard_win.winfo_exists():
            self.keyboard_win.deiconify()
            self.keyboard_win.lift()
            self.keyboard_win.focus_force()
        else:
            parent = entry.winfo_toplevel()
            self.keyboard_win = tb.Toplevel(parent)
            self.keyboard_win.title("Virtual Keyboard")
            self.keyboard_win.geometry("650x250+300+300")
            self.keyboard_win.resizable(False, False)
            self.keyboard_win.transient(parent)
            self.keyboard_win.grab_set()
            self.keyboard_win.focus_set()
            self.keyboard_win.protocol("WM_DELETE_WINDOW", self._close_keyboard)

        for w in self.keyboard_win.winfo_children():
            w.destroy()

        self.current_kb_entry = entry
        self.current_kb_var = kb_var

        # Force focus on entry with delays (critical on Raspberry Pi)
        self.after(30, entry.focus_set)
        self.after(80, entry.focus_force)
        self.after(150, lambda: entry.select_range(0, tk.END))
        self.after(180, lambda: entry.icursor(tk.END))

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
                    command=lambda c=char: self._kb_insert_char(c)
                ).pack(side="left", padx=3)

        bottom = tb.Frame(kb_frame)
        bottom.pack(pady=8, fill="x")

        tb.Button(bottom, text="⌫", width=8, bootstyle="warning",
                  command=self._kb_backspace).pack(side="left", padx=6)

        tb.Button(bottom, text="Space", width=24, bootstyle="secondary",
                  command=self._kb_space).pack(side="left", padx=6, expand=True, fill="x")

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

        # Bind Return key
        entry.unbind("<Return>")
        if next_widget:
            entry.bind("<Return>", lambda e: self._move_to_next(entry, next_widget))
        else:
            entry.bind("<Return>", lambda e: self._close_keyboard())

    def _close_keyboard(self):
        self._closing_keyboard = True
        if self.keyboard_win and self.keyboard_win.winfo_exists():
            self.keyboard_win.destroy()
        self.keyboard_win = None
        self.current_kb_entry = None
        self.current_kb_var = None
        self.after(200, lambda: setattr(self, "_closing_keyboard", False))

    def _kb_target_entry(self):
        if not self.current_kb_entry or not self.current_kb_entry.winfo_exists():
            return None
        try:
            self.current_kb_entry.focus_set()
            self.current_kb_entry.focus_force()
        except:
            pass
        return self.current_kb_entry

    def _kb_insert_char(self, char):
        if self.current_kb_var:
            try:
                self.current_kb_var.set(self.current_kb_var.get() + char)
                return
            except:
                self.current_kb_var = None

        entry = self._kb_target_entry()
        if entry:
            try:
                entry.insert(tk.END, char)
                entry.icursor(tk.END)
            except:
                pass

    def _kb_backspace(self):
        if self.current_kb_var:
            try:
                txt = self.current_kb_var.get()
                if txt:
                    self.current_kb_var.set(txt[:-1])
                return
            except:
                self.current_kb_var = None

        entry = self._kb_target_entry()
        if entry:
            try:
                txt = entry.get()
                if txt:
                    entry.delete(len(txt)-1, tk.END)
            except:
                pass

    def _kb_space(self):
        self._kb_insert_char(" ")

    def hide_keyboard(self):
        self._close_keyboard()

    def _move_to_next(self, current, next_widget):
        if next_widget:
            next_widget.focus_set()
            next_widget.focus_force()
            if isinstance(next_widget, (tb.Entry, tk.Entry)):
                next_widget.select_range(0, tk.END)
                next_widget.icursor(tk.END)
            self.after(120, lambda: self.show_virtual_keyboard(next_widget))
        else:
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
        name_var = tk.StringVar()
        name_entry = tb.Entry(win, width=50, font=("Helvetica", 12), textvariable=name_var)
        name_entry.pack(pady=4)

        tb.Label(win, text="Expected Text:", font=("Helvetica", 11)).pack(pady=(20, 2))
        text_var = tk.StringVar()
        text_entry = tb.Entry(win, width=50, font=("Helvetica", 12), textvariable=text_var)
        text_entry.pack(pady=4)

        name_entry.bind("<FocusIn>", lambda e: self.show_virtual_keyboard(name_entry, text_entry, name_var))
        text_entry.bind("<FocusIn>", lambda e: self.show_virtual_keyboard(text_entry, None, text_var))

        name_entry.focus()

        def next_step():
            name = name_var.get().strip()
            expected = text_var.get().strip()
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

    # ─── Archive & other methods remain unchanged ───
    # (keeping them out of this snippet for brevity – copy from your original if needed)

    def open_archive(self):
        # ... your original code ...
        pass

    def show_archive_window(self):
        # ... your original code ...
        pass

    def delete_ref(self, tree):
        # ... your original code ...
        pass

    def edit_ref(self, tree):
        # ... your original code ...
        pass

    def start_edit(self, ref):
        # ... your original code ...
        pass

    def on_mouse_down(self, event):
        self.rect_start = (event.x, event.y)

    def on_mouse_drag(self, event):
        if self.rect_start:
            x1, y1 = self.rect_start
            x2, y2 = event.x, event.y
            if abs(x2 - x1) > 10 and abs(y2 - y1) > 10:
                self.camera.set_roi_temp(x1, y1, x2 - x1, y2 - y1)

    def on_mouse_up(self, event):
        # ... your original code (very long – keep as is) ...
        pass

    def on_ref_selected(self, event=None):
        # ... your original code ...
        pass

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