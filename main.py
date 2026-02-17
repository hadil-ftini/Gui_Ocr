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
        self.title("Check Ref - Tunitech")
        self.geometry("1100x850")
        
        self.running = True
        self.references = self.load_references()
        self.adding_new_ref = False
        self.pending_ref = None

        # Virtual Keyboard State
        self.keyboard_win = None
        self.current_kb_entry = None
        self.current_kb_var = None
        self._closing_keyboard = False

        self.setup_ui()
        
        self.camera = cam.CameraApp()
        self.start_camera()
        self.update_camera()

    def setup_ui(self):
        # ─── Header ───
        self.header = tb.Frame(self, bootstyle="light")
        self.header.pack(side="top", fill="x", padx=10, pady=5)
        
        try:
            logo_img = Image.open("logo.png")
            aspect_ratio = logo_img.width / logo_img.height
            new_height = 50
            new_width = int(new_height * aspect_ratio)
            logo_img = logo_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            self.logo_tk = ImageTk.PhotoImage(logo_img)
            self.logo_label = tb.Label(self.header, image=self.logo_tk)
            self.logo_label.pack(side="left", padx=10)
        except:
            tb.Label(self.header, text="TUNITECH", font=("Helvetica", 20, "bold")).pack(side="left", padx=10)
        
        self.theme_mb = tb.Menubutton(self.header, text="Themes", bootstyle="primary")
        self.theme_mb.pack(side="right", padx=10)
        self.theme_menu = tb.Menu(self.theme_mb)
        for theme in tm.get_available_themes():
            self.theme_menu.add_command(label=theme, command=lambda t=theme: self.change_theme(t))
        self.theme_mb["menu"] = self.theme_menu

        self.ref_var = tk.StringVar()
        self.ref_combo = tb.Combobox(self.header, textvariable=self.ref_var,
                                     values=[r['name'] for r in self.references],
                                     state="readonly", width=25)
        self.ref_combo.pack(side="right", padx=10)
        self.ref_combo.bind("<<ComboboxSelected>>", self.on_ref_selected)

        # ─── Sidebar ───
        self.sidebar = tb.Frame(self, bootstyle="dark")
        self.sidebar.pack(side="left", fill="y", padx=5, pady=5)
        
        tb.Button(self.sidebar, text="⚙ Add Reference", bootstyle="success", command=self.open_settings).pack(pady=10, padx=10, fill="x")
        tb.Button(self.sidebar, text="📁 Archive", bootstyle="primary", command=self.open_archive).pack(pady=10, padx=10, fill="x")
        tb.Button(self.sidebar, text="Clear Zone", bootstyle="warning", command=self.clear_zone).pack(pady=10, padx=10, fill="x")

        # ─── Main Content ───
        self.main_content = tb.Frame(self)
        self.main_content.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        
        self.result_label = tb.Label(self.main_content, text="Ready", font=("Helvetica", 14), bootstyle="info")
        self.result_label.pack(side="bottom", pady=10)

        self.camera_frame = tb.Labelframe(self.main_content, text="Live Feed")
        self.camera_frame.pack(fill="both", expand=True)
        self.camera_label = tb.Label(self.camera_frame)
        self.camera_label.pack(fill="both", expand=True)
        
        self.camera_label.bind("<Button-1>", self.on_mouse_down)
        self.camera_label.bind("<B1-Motion>", self.on_mouse_drag)
        self.camera_label.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.rect_start = None

    # ─── VIRTUAL KEYBOARD SYSTEM (HEAVILY PROTECTED FOR PI) ───
    def show_virtual_keyboard(self, entry, next_widget=None, kb_var=None):
        if self._closing_keyboard: return
        
        self.current_kb_entry = entry
        self.current_kb_var = kb_var
        
        if not self.keyboard_win or not self.keyboard_win.winfo_exists():
            self.keyboard_win = tb.Toplevel(self)
            self.keyboard_win.title("Keyboard")
            self.keyboard_win.geometry("650x300+300+400")
            self.keyboard_win.attributes("-topmost", True)
            self.keyboard_win.resizable(False, False)
            self.keyboard_win.protocol("WM_DELETE_WINDOW", self._close_keyboard)
            
            # This makes the keyboard "Master" of the screen so it always works
            self.keyboard_win.grab_set() 
        
        self.keyboard_win.lift()
        self._refresh_kb_layout(next_widget)

    def _refresh_kb_layout(self, next_widget):
        for w in self.keyboard_win.winfo_children(): w.destroy()
        main_frame = tb.Frame(self.keyboard_win, padding=5, bootstyle="secondary")
        main_frame.pack(fill="both", expand=True)

        rows = ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
        for r_chars in rows:
            row_frame = tb.Frame(main_frame, bootstyle="secondary")
            row_frame.pack(pady=2)
            for char in r_chars:
                btn = tb.Button(row_frame, text=char, width=5, bootstyle="light-outline",
                               command=lambda c=char: self._kb_insert_char(c))
                btn.pack(side="left", padx=2, ipady=4)

        ctrl_row = tb.Frame(main_frame, bootstyle="secondary")
        ctrl_row.pack(pady=8, fill="x", padx=10)

        tb.Button(ctrl_row, text="⌫", width=8, bootstyle="danger-outline", 
                  command=self._kb_backspace).pack(side="left", padx=2, ipady=5)
        
        tb.Button(ctrl_row, text="SPACE", bootstyle="light", 
                  command=self._kb_space).pack(side="left", padx=2, expand=True, fill="x", ipady=5)
        
        if next_widget:
            cmd = lambda: self._move_to_next(self.current_kb_entry, next_widget)
            btn_text, btn_style = "NEXT →", "success"
        else:
            cmd = self._close_keyboard
            btn_text, btn_style = "✔ DONE", "primary"

        tb.Button(ctrl_row, text=btn_text, width=10, bootstyle=btn_style, 
                  command=cmd).pack(side="right", padx=2, ipady=5)

    def _move_to_next(self, current, next_widget):
        # Release control briefly to switch fields
        if self.keyboard_win: self.keyboard_win.grab_release()
        next_widget.focus_set()
        if isinstance(next_widget, (tb.Entry, tk.Entry)):
            next_widget.select_range(0, tk.END)
            next_widget.icursor(tk.END)
        self.show_virtual_keyboard(next_widget, kb_var=getattr(next_widget, 'associated_var', None))

    def _kb_insert_char(self, char):
        if self.current_kb_var: self.current_kb_var.set(self.current_kb_var.get() + char)

    def _kb_backspace(self):
        if self.current_kb_var: self.current_kb_var.set(self.current_kb_var.get()[:-1])

    def _kb_space(self): self._kb_insert_char(" ")

    def _close_keyboard(self):
        self._closing_keyboard = True
        if self.keyboard_win:
            self.keyboard_win.grab_release() # Very important!
            if self.keyboard_win.winfo_exists():
                self.keyboard_win.destroy()
            self.keyboard_win = None
        self.after(300, lambda: setattr(self, "_closing_keyboard", False))

    # ─── SETTINGS ───
    def open_settings(self):
        win = tb.Toplevel(self)
        win.title("Reference Setup")
        win.geometry("520x340+50+50")
        win.attributes("-topmost", True)
        
        container = tb.Frame(win, padding=25)
        container.pack(fill="both", expand=True)

        name_var = tk.StringVar()
        e1 = tb.Entry(container, textvariable=name_var); e1.pack(fill="x", pady=10)
        e1.associated_var = name_var

        text_var = tk.StringVar()
        e2 = tb.Entry(container, textvariable=text_var); e2.pack(fill="x", pady=10)
        e2.associated_var = text_var

        e1.bind("<Button-1>", lambda e: self.after(100, lambda: self.show_virtual_keyboard(e1, e2, name_var)))
        e2.bind("<Button-1>", lambda e: self.after(100, lambda: self.show_virtual_keyboard(e2, None, text_var)))

        def confirm():
            if name_var.get() and text_var.get():
                self.pending_ref = {"name": name_var.get(), "expected_text": text_var.get(), "roi": None}
                self.adding_new_ref = True
                self._close_keyboard()
                win.destroy()
        tb.Button(container, text="CONTINUE", command=confirm).pack()

    # ─── ARCHIVE (THE PASSWORD FIX) ───
    def open_archive(self):
        pwd_win = tb.Toplevel(self)
        pwd_win.title("Password")
        pwd_win.geometry("300x200")
        pwd_win.attributes("-topmost", True)
        pwd_win.position_center()

        pwd_var = tk.StringVar()
        # Setting associated_var before the bind
        pwd_entry = tb.Entry(pwd_win, textvariable=pwd_var, show="*")
        pwd_entry.associated_var = pwd_var 
        pwd_entry.pack(pady=20, padx=20, fill="x")
        
        # This force-links the entry and opens keyboard
        pwd_entry.bind("<Button-1>", lambda e: self.after(100, lambda: [pwd_entry.focus_set(), self.show_virtual_keyboard(pwd_entry, None, pwd_var)]))

        def check_password():
            if pwd_var.get() == "TUNITECH":
                pwd_win.destroy()
                self._close_keyboard()
                self.show_archive_manager()
            else:
                tb.dialogs.Messagebox.show_error("Wrong Password", "Denied", parent=pwd_win)

        tb.Button(pwd_win, text="Login", command=check_password).pack()

    def show_archive_manager(self):
        win = tb.Toplevel(self)
        win.title("Archive")
        win.geometry("800x600")
        
        cols = ("name", "text")
        tree = tb.Treeview(win, columns=cols, show="headings")
        tree.heading("name", text="Name"); tree.heading("text", text="Text")
        tree.pack(fill="both", expand=True)

        for r in self.references:
            tree.insert("", "end", values=(r["name"], r["expected_text"]))

        def edit_item():
            sel = tree.selection()
            if not sel: return
            old_name = tree.item(sel[0])["values"][0]
            ref_data = next(r for r in self.references if r["name"] == old_name)
            
            edit_win = tb.Toplevel(win)
            edit_win.geometry("400x300")
            
            n_var = tk.StringVar(value=ref_data["name"])
            en = tb.Entry(edit_win, textvariable=n_var); en.pack(pady=10)
            en.associated_var = n_var
            
            t_var = tk.StringVar(value=ref_data["expected_text"])
            et = tb.Entry(edit_win, textvariable=t_var); et.pack(pady=10)
            et.associated_var = t_var

            en.bind("<Button-1>", lambda e: self.after(100, lambda: self.show_virtual_keyboard(en, et, n_var)))
            et.bind("<Button-1>", lambda e: self.after(100, lambda: self.show_virtual_keyboard(et, None, t_var)))

            def save():
                ref_data["name"], ref_data["expected_text"] = n_var.get(), t_var.get()
                self.save_references(); edit_win.destroy(); self._close_keyboard()
            tb.Button(edit_win, text="Save", command=save).pack()

        tb.Button(win, text="Edit", command=edit_item).pack(side="left")

    # ─── REMAINING CAMERA/MOUSE LOGIC ───
    def on_mouse_up(self, event):
        if not self.rect_start: return
        x1, y1 = self.rect_start
        scale = 1 / self.camera.display_scale
        rx, ry = int(min(x1, event.x) * scale), int(min(y1, event.y) * scale)
        rw, rh = int(abs(event.x - x1) * scale), int(abs(event.y - y1) * scale)
        if self.adding_new_ref and self.pending_ref:
            self.pending_ref["roi"] = (rx, ry, rw, rh)
            self.references.append(self.pending_ref)
            self.save_references(); self.update_ref_combo()
            self.camera.clear_roi(); self.adding_new_ref = False
        self.rect_start = None

    def load_references(self):
        if os.path.exists("references.json"):
            with open("references.json", "r") as f: return json.load(f)
        return []
    def save_references(self):
        with open("references.json", "w") as f: json.dump(self.references, f, indent=4)
    def update_ref_combo(self): self.ref_combo['values'] = [r['name'] for r in self.references]
    def on_ref_selected(self, event):
        for r in self.references:
            if r["name"] == self.ref_var.get():
                self.camera.set_roi(*r["roi"]); self.camera.expected_text = r["expected_text"]
    def start_camera(self): self.camera.start_camera(0)
    def update_camera(self):
        if self.running and self.camera.is_running:
            img = self.camera.get_frame()
            if img: self.camera_label.configure(image=img); self.camera_label.image = img
        self.after(30, self.update_camera)
    def on_mouse_down(self, event): self.rect_start = (event.x, event.y)
    def on_mouse_drag(self, event):
        if self.rect_start: self.camera.set_roi_temp(self.rect_start[0], self.rect_start[1], event.x - self.rect_start[0], event.y - self.rect_start[1])
    def change_theme(self, name): tm.set_theme(self, name)
    def clear_zone(self): self.camera.clear_roi()

if __name__ == "__main__":
    app = MainApp()
    app.mainloop()