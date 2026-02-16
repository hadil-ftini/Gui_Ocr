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

        self.keyboard_win = None
        self.current_kb_var = None
        self._closing_keyboard = False

        self.setup_ui()
        self.camera = cam.CameraApp()
        self.start_camera()
        self.update_camera()

    def setup_ui(self):
        self.header = tb.Frame(self, bootstyle="light")
        self.header.pack(side="top", fill="x", padx=10, pady=5)
        
        try:
            logo_img = Image.open("logo.png")
            ratio = logo_img.width / logo_img.height
            logo_img = logo_img.resize((int(50*ratio), 50), Image.Resampling.LANCZOS)
            self.logo_tk = ImageTk.PhotoImage(logo_img)
            tb.Label(self.header, image=self.logo_tk).pack(side="left", padx=10)
        except:
            tb.Label(self.header, text="TUNITECH", font=("Helvetica", 20, "bold")).pack(side="left", padx=10)
        
        self.ref_var = tk.StringVar()
        self.ref_combo = tb.Combobox(self.header, textvariable=self.ref_var, state="readonly", width=25)
        self.ref_combo.pack(side="right", padx=10)
        self.update_ref_combo()
        self.ref_combo.bind("<<ComboboxSelected>>", self.on_ref_selected)

        self.sidebar = tb.Frame(self, bootstyle="dark")
        self.sidebar.pack(side="left", fill="y", padx=5, pady=5)
        tb.Button(self.sidebar, text="⚙ Add Reference", bootstyle="success", command=self.open_settings).pack(pady=10, padx=10, fill="x")
        tb.Button(self.sidebar, text="📁 Archive", bootstyle="primary", command=self.open_archive).pack(pady=10, padx=10, fill="x")
        tb.Button(self.sidebar, text="Clear Zone", bootstyle="warning", command=self.clear_zone).pack(pady=10, padx=10, fill="x")

        self.main_content = tb.Frame(self)
        self.main_content.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        self.result_label = tb.Label(self.main_content, text="Ready", font=("Helvetica", 14), bootstyle="info")
        self.result_label.pack(side="bottom", pady=10)

        self.camera_label = tb.Label(self.main_content)
        self.camera_label.pack(fill="both", expand=True)
        self.camera_label.bind("<Button-1>", self.on_mouse_down)
        self.camera_label.bind("<B1-Motion>", self.on_mouse_drag)
        self.camera_label.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.rect_start = None

    # --- Keyboard Logic ---
    def show_virtual_keyboard(self, entry, next_widget=None, kb_var=None):
        if self._closing_keyboard: return
        self.current_kb_var = kb_var
        if not self.keyboard_win or not self.keyboard_win.winfo_exists():
            self.keyboard_win = tb.Toplevel(self)
            self.keyboard_win.title("Keyboard")
            self.keyboard_win.geometry("650x250+300+400")
            self.keyboard_win.attributes("-topmost", True)
            self.keyboard_win.resizable(False, False)
        
        for w in self.keyboard_win.winfo_children(): w.destroy()
        frame = tb.Frame(self.keyboard_win, padding=5, bootstyle="secondary")
        frame.pack(fill="both", expand=True)

        rows = ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
        for r in rows:
            row_f = tb.Frame(frame, bootstyle="secondary")
            row_f.pack(pady=2)
            for c in r:
                tb.Button(row_f, text=c, width=5, bootstyle="light-outline", 
                          command=lambda char=c: self.current_kb_var.set(self.current_kb_var.get()+char)).pack(side="left", padx=2)

        ctrl = tb.Frame(frame, bootstyle="secondary")
        ctrl.pack(pady=10, fill="x")
        tb.Button(ctrl, text="⌫", width=8, bootstyle="danger", command=lambda: self.current_kb_var.set(self.current_kb_var.get()[:-1])).pack(side="left", padx=5)
        
        if next_widget:
            tb.Button(ctrl, text="NEXT →", bootstyle="success", command=lambda: next_widget.focus_set()).pack(side="right", padx=5)
        else:
            tb.Button(ctrl, text="✔ DONE", bootstyle="primary", command=self._close_keyboard).pack(side="right", padx=5)

    def _close_keyboard(self):
        if self.keyboard_win:
            self.keyboard_win.destroy()
            self.keyboard_win = None

    # --- Settings (Fixed Placement & Auto-Keyboard Close) ---
    def open_settings(self):
        self.camera.clear_roi() # Clean camera for new drawing
        win = tb.Toplevel(self)
        win.title("Reference Setup")
        win.geometry("520x340+50+50") # Top Left
        
        # When this window is closed/destroyed, close the keyboard too
        win.bind("<Destroy>", lambda e: self._close_keyboard() if e.widget == win else None)

        container = tb.Frame(win, padding=20)
        container.pack(fill="both", expand=True)

        tb.Label(container, text="Name:").pack(anchor="w")
        n_var = tk.StringVar(); e1 = tb.Entry(container, textvariable=n_var)
        e1.pack(fill="x", pady=5); e1.associated_var = n_var
        
        tb.Label(container, text="Expected Text:").pack(anchor="w")
        t_var = tk.StringVar(); e2 = tb.Entry(container, textvariable=t_var)
        e2.pack(fill="x", pady=5); e2.associated_var = t_var

        e1.bind("<FocusIn>", lambda e: self.show_virtual_keyboard(e1, e2, n_var))
        e2.bind("<FocusIn>", lambda e: self.show_virtual_keyboard(e2, None, t_var))

        def confirm():
            if n_var.get() and t_var.get():
                self.pending_ref = {"name": n_var.get(), "expected_text": t_var.get()}
                self.adding_new_ref = True
                win.destroy()
                self.result_label.configure(text=f"Draw ROI for {n_var.get()}", bootstyle="warning")

        tb.Button(container, text="CONTINUE TO ROI", bootstyle="success", command=confirm).pack(pady=20)

    # --- Mouse Logic ---
    def on_mouse_down(self, event): self.rect_start = (event.x, event.y)
    
    def on_mouse_drag(self, event):
        if self.rect_start:
            x1, y1 = self.rect_start
            self.camera.set_roi_temp(x1, y1, event.x - x1, event.y - y1)

    def on_mouse_up(self, event):
        if not self.rect_start: return
        x1, y1 = self.rect_start
        scale = 1 / self.camera.display_scale
        rx, ry = int(min(x1, event.x)*scale), int(min(y1, event.y)*scale)
        rw, rh = int(abs(event.x-x1)*scale), int(abs(event.y-y1)*scale)
        
        self.camera.temp_roi = None
        self.rect_start = None

        if self.adding_new_ref and self.pending_ref:
            self.pending_ref["roi"] = (rx, ry, rw, rh)
            self.references.append(self.pending_ref)
            self.save_references()
            self.camera.set_roi(rx, ry, rw, rh)
            self.update_ref_combo()
            
            tb.dialogs.Messagebox.show_info(f"Ref '{self.pending_ref['name']}' Saved!", "Success")
            self.result_label.configure(text=f"Active: {self.pending_ref['name']}", bootstyle="success")
            self.adding_new_ref = False
        else:
            self.camera.set_roi(rx, ry, rw, rh)

    def update_camera(self):
        if self.running and self.camera.is_running:
            img = self.camera.get_frame()
            if img: self.camera_label.configure(image=img); self.camera_label.image = img
        self.after(30, self.update_camera)

    def load_references(self):
        if os.path.exists("references.json"):
            with open("references.json", "r") as f: return json.load(f)
        return []

    def save_references(self):
        with open("references.json", "w") as f: json.dump(self.references, f, indent=4)

    def update_ref_combo(self):
        self.ref_combo['values'] = [r['name'] for r in self.references]

    def on_ref_selected(self, event):
        for r in self.references:
            if r["name"] == self.ref_var.get():
                self.camera.set_roi(*r["roi"])
                self.camera.expected_text = r["expected_text"]

    def open_archive(self):
        win = tb.Toplevel(self); win.geometry("400x300")
        tree = tb.Treeview(win, columns=("name"), show="headings")
        tree.heading("name", text="Reference Name"); tree.pack(fill="both", expand=True)
        for r in self.references: tree.insert("", "end", values=(r["name"],))
        
    def start_camera(self): self.camera.start_camera(0)
    def clear_zone(self): self.camera.clear_roi()

if __name__ == "__main__":
    app = MainApp()
    app.mainloop()