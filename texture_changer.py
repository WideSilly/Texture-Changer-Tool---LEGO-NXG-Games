"""
GSC Texture Tool (.pyw)

Features:
- Select a .gsc file and count occurrences of "DDS" (defines number of textures)
- Select Texture {1..N} (textures are bytes starting at each "DDS" and ending at the next "DDS" or the next "NUT")
- Show the selected texture (attempts to load DDS via Pillow)
- Export selected texture as .dds
- Change selected texture by selecting a .dds file; original file is backed up as file.gsc.bak before saving
- Delete selected texture; original file is backed up as file.gsc.bak before saving

Notes:
- This script tries to preview DDS files using Pillow. For DDS support you may need the pillow-dds plugin
  (pip install pillow-dds) or use an installed Pillow build that supports DDS. If preview fails, the tool still
  allows Export/Change/Delete operations on the raw bytes.
- Use Python 3.8+ and run as a .pyw (no console) or .py for debugging.

"""

import os
import shutil
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


class GSCTextureTool(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Texture Changer")
        self.geometry("820x520")

        # state
        self.gsc_path = None
        self.gsc_bytes = None
        self.texture_ranges = []  # list of (start, end) byte offsets
        self.current_texture_index = None
        self.preview_image = None  # keep reference to PhotoImage

        # UI
        self.create_widgets()

    def create_widgets(self):
        frame_top = ttk.Frame(self)
        frame_top.pack(fill=tk.X, padx=8, pady=8)

        btn_select_gsc = ttk.Button(frame_top, text="Select GSC", command=self.select_gsc)
        btn_select_gsc.pack(side=tk.LEFT)

        self.lbl_count = ttk.Label(frame_top, text="No GSC selected")
        self.lbl_count.pack(side=tk.LEFT, padx=12)

        # Texture selection
        frame_mid = ttk.Frame(self)
        frame_mid.pack(fill=tk.X, padx=8, pady=6)

        ttk.Label(frame_mid, text="Select Texture:").pack(side=tk.LEFT)
        self.texture_var = tk.StringVar()
        self.texture_combo = ttk.Combobox(frame_mid, textvariable=self.texture_var, state="readonly", width=20)
        self.texture_combo.pack(side=tk.LEFT, padx=6)
        self.texture_combo.bind("<<ComboboxSelected>>", lambda e: self.on_texture_selected())

        btn_export = ttk.Button(frame_mid, text="Export Texture", command=self.export_texture)
        btn_export.pack(side=tk.LEFT, padx=6)

        btn_change = ttk.Button(frame_mid, text="Change Texture", command=self.change_texture)
        btn_change.pack(side=tk.LEFT, padx=6)

        btn_delete = ttk.Button(frame_mid, text="Delete Texture", command=self.delete_texture)
        btn_delete.pack(side=tk.LEFT, padx=6)

        # Preview area and info
        frame_bottom = ttk.Frame(self)
        frame_bottom.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Left: preview canvas
        preview_frame = ttk.LabelFrame(frame_bottom, text="Texture Preview")
        preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,8))

        self.canvas = tk.Canvas(preview_frame, bg="#333333")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Right: hex/metadata & status
        info_frame = ttk.LabelFrame(frame_bottom, text="Texture Info / Raw Preview")
        info_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, ipadx=4, ipady=4)
        info_frame.config(width=300)

        self.txt_info = tk.Text(info_frame, width=46, height=30)
        self.txt_info.pack(fill=tk.BOTH, expand=True)
        self.txt_info.config(state=tk.DISABLED)

        # Status
        self.status_var = tk.StringVar(value="Ready")
        self.lbl_status = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        self.lbl_status.pack(fill=tk.X, side=tk.BOTTOM)

    def set_status(self, text):
        self.status_var.set(text)

    def select_gsc(self):
        path = filedialog.askopenfilename(title="Select .gsc file", filetypes=[("GSC files", "*.gsc"), ("All files", "*")])
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open file:\n{e}")
            return

        self.gsc_path = path
        self.gsc_bytes = data
        self.parse_textures()
        self.update_texture_list()
        self.set_status(f"Loaded: {os.path.basename(path)}")

    def parse_textures(self):
        """Parse self.gsc_bytes to find texture ranges.

        Rule implemented (best-effort based on your description):
        - Find all occurrences of the ASCII sequence b"DDS" (case-sensitive).
        - Each occurrence is treated as the start of a texture.
        - The texture ends at the next occurrence of b"DDS" (start of next texture) or at the first occurrence of b"NUT" after the start.
        - If neither is found, the texture continues to end of file.

        This is a heuristic — adjust as needed for your exact GSC layout.
        """
        data = self.gsc_bytes
        self.texture_ranges = []
        if not data:
            return

        starts = []
        idx = 0
        needle = b"DDS"
        while True:
            i = data.find(needle, idx)
            if i == -1:
                break
            starts.append(i)
            idx = i + len(needle)

        # build ranges
        for k, start in enumerate(starts):
            # candidate end: next start
            if k + 1 < len(starts):
                end_candidate = starts[k + 1]
            else:
                end_candidate = None

            nut_idx = data.find(b"NUT", start)
            if nut_idx != -1:
                if end_candidate is None:
                    end = nut_idx
                else:
                    end = min(end_candidate, nut_idx)
            else:
                end = end_candidate if end_candidate is not None else len(data)

            # safety: ensure end > start
            if end <= start:
                end = start + 1

            self.texture_ranges.append((start, end))

    def update_texture_list(self):
        count = len(self.texture_ranges)
        if count == 0:
            self.lbl_count.config(text="No textures (no 'DDS' found)")
            self.texture_combo['values'] = []
            self.texture_var.set("")
            self.clear_preview()
            return

        self.lbl_count.config(text=f"Textures found: {count}")
        vals = [f"Texture {i+1}" for i in range(count)]
        self.texture_combo['values'] = vals
        # select first by default
        self.texture_combo.current(0)
        self.on_texture_selected()

    def on_texture_selected(self):
        sel = self.texture_combo.current()
        if sel < 0:
            return
        self.current_texture_index = sel
        self.show_texture(sel)

    def clear_preview(self):
        self.canvas.delete("all")
        self.txt_info.config(state=tk.NORMAL)
        self.txt_info.delete(1.0, tk.END)
        self.txt_info.config(state=tk.DISABLED)
        self.preview_image = None

    def show_texture(self, index):
        self.clear_preview()
        start, end = self.texture_ranges[index]
        tex_bytes = self.gsc_bytes[start:end]

        # Info
        info_text = f"Texture {index+1}\nStart: {start}\nEnd: {end}\nSize: {len(tex_bytes)} bytes\n\nFirst 256 bytes (hex):\n"
        hex_preview = tex_bytes[:256].hex(' ', 1)
        info_text += hex_preview

        self.txt_info.config(state=tk.NORMAL)
        self.txt_info.insert(tk.END, info_text)
        self.txt_info.config(state=tk.DISABLED)

        # Try to preview image using Pillow
        if PIL_AVAILABLE:
            try:
                tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dds')
                os.close(tmp_fd)
                with open(tmp_path, 'wb') as t:
                    t.write(tex_bytes)

                # attempt to load
                img = Image.open(tmp_path)
                img.load()
                # ensure canvas size is up-to-date
                self.canvas.update_idletasks()
                cw = self.canvas.winfo_width() or 400
                ch = self.canvas.winfo_height() or 300
                # COVER-style scaling: scale the image so it completely fills the canvas (may crop edges)
                iw, ih = img.size
                scale = max((cw-4) / iw, (ch-4) / ih)
                new_w = max(1, int(iw * scale))
                new_h = max(1, int(ih * scale))
                # Use high-quality resampling when available
                resample = getattr(Image, 'Resampling', None)
                if resample is not None:
                    img = img.resize((new_w, new_h), resample.LANCZOS)
                else:
                    img = img.resize((new_w, new_h), Image.LANCZOS)
                # center-crop to exactly the canvas size (minus a small padding)
                left = (new_w - (cw-4)) // 2
                top = (new_h - (ch-4)) // 2
                right = left + (cw-4)
                bottom = top + (ch-4)
                img = img.crop((left, top, right, bottom))
                self.preview_image = ImageTk.PhotoImage(img)
                self.canvas.create_image((cw//2, ch//2), image=self.preview_image, anchor=tk.CENTER)

                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                self.set_status("Preview loaded (requires Pillow with DDS support)")
                return
            except Exception as e:
                # fall through to non-image display
                self.set_status(f"Preview failed: {e}")
        else:
            self.set_status("Pillow not available — Install pillow and pillow-dds for image preview")

    def export_texture(self):
        if self.gsc_path is None or self.current_texture_index is None:
            messagebox.showinfo("Info", "Select a GSC and a texture first")
            return
        start, end = self.texture_ranges[self.current_texture_index]
        tex_bytes = self.gsc_bytes[start:end]
        suggested = os.path.splitext(os.path.basename(self.gsc_path))[0] + f"_texture_{self.current_texture_index+1}.dds"
        out = filedialog.asksaveasfilename(title="Export texture as", defaultextension='.dds', initialfile=suggested, filetypes=[("DDS files","*.dds"), ("All files","*")])
        if not out:
            return
        try:
            with open(out, 'wb') as f:
                f.write(tex_bytes)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export texture:\n{e}")
            return
        self.set_status(f"Exported texture to {out}")

    def change_texture(self):
        if self.gsc_path is None or self.current_texture_index is None:
            messagebox.showinfo("Info", "Select a GSC and a texture first")
            return
        new_file = filedialog.askopenfilename(title="Select .dds file to replace texture", filetypes=[("DDS files","*.dds"), ("All files","*")])
        if not new_file:
            return
        try:
            with open(new_file, 'rb') as f:
                new_bytes = f.read()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open new texture file:\n{e}")
            return

        # backup original
        bak_path = self.gsc_path + '.bak'
        try:
            shutil.copy2(self.gsc_path, bak_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create backup file ({bak_path}):\n{e}")
            return

        # Replace bytes in memory and write file
        start, end = self.texture_ranges[self.current_texture_index]
        new_data = self.gsc_bytes[:start] + new_bytes + self.gsc_bytes[end:]

        try:
            with open(self.gsc_path, 'wb') as f:
                f.write(new_data)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to write updated GSC file:\n{e}")
            # attempt to restore from backup
            try:
                shutil.copy2(bak_path, self.gsc_path)
                messagebox.showinfo("Restore", "Original file restored from backup")
            except Exception:
                messagebox.showwarning("Warning", "Failed to restore original from backup — manual restore may be required")
            return

        # reload
        try:
            with open(self.gsc_path, 'rb') as f:
                self.gsc_bytes = f.read()
        except Exception as e:
            messagebox.showwarning("Warning", f"Saved but failed to reload file:\n{e}")
            self.set_status("Saved (could not reload)")
            return

        # reparsed textures
        self.parse_textures()
        # keep the same logical texture index if possible, else clamp
        new_count = len(self.texture_ranges)
        if new_count == 0:
            self.texture_combo['values'] = []
            self.texture_var.set("")
            self.clear_preview()
            self.set_status(f"Replaced texture and saved. Backup: {bak_path}")
            return

        if self.current_texture_index >= new_count:
            self.current_texture_index = new_count - 1
        self.update_texture_list()
        # set selection to the replaced texture if possible
        if self.current_texture_index is not None:
            self.texture_combo.current(self.current_texture_index)
            self.show_texture(self.current_texture_index)

        self.set_status(f"Texture replaced and file saved. Backup: {bak_path}")
        
    def delete_texture(self):
        if self.gsc_path is None or self.current_texture_index is None:
            messagebox.showinfo("Info", "Select a GSC and a texture first")
            return

        # backup original
        bak_path = self.gsc_path + '.bak'
        try:
            shutil.copy2(self.gsc_path, bak_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create backup file ({bak_path}):\n{e}")
            return

        # Replace bytes in memory and write file
        start, end = self.texture_ranges[self.current_texture_index]
        new_data = self.gsc_bytes[:start] + self.gsc_bytes[end:]

        try:
            with open(self.gsc_path, 'wb') as f:
                f.write(new_data)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to write updated GSC file:\n{e}")
            # attempt to restore from backup
            try:
                shutil.copy2(bak_path, self.gsc_path)
                messagebox.showinfo("Restore", "Original file restored from backup")
            except Exception:
                messagebox.showwarning("Warning", "Failed to restore original from backup — manual restore may be required")
            return

        # reload
        try:
            with open(self.gsc_path, 'rb') as f:
                self.gsc_bytes = f.read()
        except Exception as e:
            messagebox.showwarning("Warning", f"Saved but failed to reload file:\n{e}")
            self.set_status("Saved (could not reload)")
            return

        # reparsed textures
        self.parse_textures()
        # keep the same logical texture index if possible, else clamp
        new_count = len(self.texture_ranges)
        if new_count == 0:
            self.texture_combo['values'] = []
            self.texture_var.set("")
            self.clear_preview()
            self.set_status(f"Replaced texture and saved. Backup: {bak_path}")
            return

        if self.current_texture_index >= new_count:
            self.current_texture_index = new_count - 1
        self.update_texture_list()
        # set selection to the replaced texture if possible
        if self.current_texture_index is not None:
            self.texture_combo.current(self.current_texture_index)
            self.show_texture(self.current_texture_index)

        self.set_status(f"Texture replaced and file saved. Backup: {bak_path}")


if __name__ == '__main__':
    app = GSCTextureTool()
    app.mainloop()
