import json
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".yt_dlp_gui.json")

BG = "#0a0a0a"
FG = "#e8e8e8"
DIM = "#8a8a8a"
ERR = "#ff5555"
FONT = ("Consolas", 10)
FONT_SMALL = ("Consolas", 9)

BANNER = r"""
 __   _______       ____  _     ____
 \ \ / /_   _|     |  _ \| |   |  _ \
  \ V /  | |  ____ | | | | |   | |_) |
   | |   | |  |____|| |_| | |___|  __/
   |_|   |_|       |____/|_____|_|
""".strip("\n")

SPINNER = "|/-\\"
PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)%")
BAR_W = 30

MARKS = {
    "pending": "[ ]",
    "running": "[>]",
    "ok": "[x]",
    "failed": "[!]",
    "aborted": "[-]",
}


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


class AsciiButton(tk.Label):
    """Bottone testuale in stile [ ETICHETTA ] con inversione colori in hover."""

    def __init__(self, master, text, command):
        super().__init__(
            master, text=f"[ {text} ]", font=FONT, bg=BG, fg=FG, cursor="hand2", padx=2
        )
        self.command = command
        self.enabled = True
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)

    def _enter(self, _):
        if self.enabled:
            self.configure(bg=FG, fg=BG)

    def _leave(self, _):
        self.configure(bg=BG, fg=FG if self.enabled else DIM)

    def _click(self, _):
        if self.enabled:
            self.command()

    def set_enabled(self, value):
        self.enabled = value
        self.configure(bg=BG, fg=FG if value else DIM, cursor="hand2" if value else "arrow")


def rule(master, title=""):
    """Linea orizzontale ASCII che si adatta alla larghezza della finestra."""
    text = "+-" + (f"[ {title} ]" if title else "") + "-" * 400
    return tk.Label(master, text=text, font=FONT, bg=BG, fg=DIM, anchor="w", width=1)


def make_entry(master, var, width=1):
    return tk.Entry(
        master,
        textvariable=var,
        font=FONT,
        bg=BG,
        fg=FG,
        insertbackground=FG,
        selectbackground=FG,
        selectforeground=BG,
        relief="flat",
        highlightthickness=1,
        highlightbackground=DIM,
        highlightcolor=FG,
        width=width,
    )


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("yt-dlp :: ascii mode")
        self.configure(bg=BG)
        self.geometry("820x720")
        self.minsize(680, 560)

        self.config_data = load_config()
        self.process = None
        self.running = False
        self.paused = False
        self.abort_req = False
        self.items = []  # ogni elemento: dict(url, dest, n, status)
        self.percent = 0.0
        self.spin_i = 0

        self.url_var = tk.StringVar()
        self.dest_var = tk.StringVar(
            value=self.config_data.get(
                "dest", os.path.join(os.path.expanduser("~"), "Downloads")
            )
        )
        self.threads_var = tk.StringVar(value=str(self.config_data.get("threads", 16)))

        root = tk.Frame(self, bg=BG, padx=12, pady=8)
        root.pack(fill="both", expand=True)

        tk.Label(
            root, text=BANNER, font=("Consolas", 10, "bold"), bg=BG, fg=FG, justify="left", anchor="w"
        ).pack(fill="x")
        tk.Label(
            root, text="fedelogo designed that!", font=FONT, bg=BG, fg=FG, anchor="w"
        ).pack(fill="x")
        tk.Label(
            root, text=">> downloader  //  yt-dlp -N 16", font=FONT_SMALL, bg=BG, fg=DIM, anchor="w"
        ).pack(fill="x", pady=(0, 6))

        # --- INPUT ---
        rule(root, "INPUT").pack(fill="x")
        grid = tk.Frame(root, bg=BG)
        grid.pack(fill="x", pady=4)
        grid.columnconfigure(1, weight=1)

        tk.Label(grid, text="URL  >", font=FONT, bg=BG, fg=FG).grid(row=0, column=0, sticky="w")
        self.url_entry = make_entry(grid, self.url_var)
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=3, ipady=2)
        AsciiButton(grid, "PASTE", self.paste_url).grid(row=0, column=2)

        tk.Label(grid, text="DEST >", font=FONT, bg=BG, fg=FG).grid(row=1, column=0, sticky="w")
        make_entry(grid, self.dest_var).grid(row=1, column=1, sticky="ew", padx=8, pady=3, ipady=2)
        AsciiButton(grid, "BROWSE", self.browse).grid(row=1, column=2)

        tk.Label(grid, text="-N   >", font=FONT, bg=BG, fg=FG).grid(row=2, column=0, sticky="w")
        make_entry(grid, self.threads_var, width=5).grid(
            row=2, column=1, sticky="w", padx=8, pady=3, ipady=2
        )

        # --- AZIONI ---
        rule(root, "ACTION").pack(fill="x")
        actions = tk.Frame(root, bg=BG)
        actions.pack(fill="x", pady=4)
        AsciiButton(actions, "ADD TO QUEUE", self.add).pack(side="left")
        AsciiButton(actions, "START", self.start_queue).pack(side="left", padx=10)
        self.stop_btn = AsciiButton(actions, "ABORT", self.stop)
        self.stop_btn.pack(side="left")
        self.stop_btn.set_enabled(False)

        self.bar_label = tk.Label(root, text="", font=FONT, bg=BG, fg=FG, anchor="w")
        self.bar_label.pack(fill="x")
        self.draw_bar()

        # --- CODA ---
        rule(root, "QUEUE").pack(fill="x", pady=(4, 0))
        qframe = tk.Frame(root, bg=BG)
        qframe.pack(fill="x")
        self.listbox = tk.Listbox(
            qframe,
            font=FONT_SMALL,
            height=7,
            bg=BG,
            fg=FG,
            selectbackground=FG,
            selectforeground=BG,
            relief="flat",
            highlightthickness=1,
            highlightbackground=DIM,
            highlightcolor=FG,
            activestyle="none",
            exportselection=False,
        )
        qsb = tk.Scrollbar(qframe, command=self.listbox.yview, bg=BG, troughcolor=BG, relief="flat")
        self.listbox.configure(yscrollcommand=qsb.set)
        qsb.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="x", expand=True)

        qbtns = tk.Frame(root, bg=BG)
        qbtns.pack(fill="x", pady=4)
        AsciiButton(qbtns, "REMOVE", self.remove_selected).pack(side="left")
        AsciiButton(qbtns, "CLEAR DONE", self.clear_done).pack(side="left", padx=10)
        tk.Label(
            qbtns, text="[ ] attesa  [>] in corso  [x] ok  [!] errore  [-] annullato",
            font=FONT_SMALL, bg=BG, fg=DIM,
        ).pack(side="right")

        # --- LOG ---
        rule(root, "LOG").pack(fill="x", pady=(4, 0))
        log_frame = tk.Frame(root, bg=BG)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_frame,
            font=FONT_SMALL,
            bg=BG,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            highlightthickness=0,
            wrap="word",
            state="disabled",
        )
        sb = tk.Scrollbar(log_frame, command=self.log.yview, bg=BG, troughcolor=BG, relief="flat")
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("err", foreground=ERR)
        self.log.tag_configure("dim", foreground=DIM)

        rule(root).pack(fill="x")

        self.write_log("ready_\n", "dim")
        self.url_entry.focus()
        self.bind("<Return>", lambda e: self.add())

    # ---------- UI helpers ----------
    def draw_bar(self):
        filled = int(BAR_W * self.percent / 100)
        bar = "#" * filled + "." * (BAR_W - filled)
        spin = SPINNER[self.spin_i % 4] if self.running else " "
        done = sum(1 for i in self.items if i["status"] == "ok")
        state = "  (in pausa)" if self.paused and not self.running else ""
        self.bar_label.configure(
            text=f"[{bar}] {self.percent:5.1f}% {spin}  coda {done}/{len(self.items)}{state}"
        )

    def tick(self):
        if self.running:
            self.spin_i += 1
            self.draw_bar()
            self.after(120, self.tick)

    def write_log(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text, tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def refresh_list(self):
        sel = self.listbox.curselection()
        self.listbox.delete(0, "end")
        for it in self.items:
            self.listbox.insert(
                "end", f"{MARKS[it['status']]} {it['url']}  >> {it['dest']}"
            )
        for i in sel:
            if i < self.listbox.size():
                self.listbox.selection_set(i)
        self.draw_bar()

    def paste_url(self):
        try:
            self.url_var.set(self.clipboard_get().strip().splitlines()[0].strip())
        except (tk.TclError, IndexError):
            pass

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.dest_var.get() or None)
        if d:
            self.dest_var.set(os.path.normpath(d))

    # ---------- Coda ----------
    def add(self):
        url = self.url_var.get().strip()
        dest = self.dest_var.get().strip()
        if not url:
            messagebox.showwarning("URL mancante", "Inserisci un URL.")
            return
        if not dest:
            messagebox.showwarning("Destinazione mancante", "Scegli una cartella di destinazione.")
            return
        try:
            n = max(1, int(self.threads_var.get()))
        except ValueError:
            n = 16
        if not shutil.which("yt-dlp"):
            messagebox.showerror(
                "yt-dlp non trovato",
                "yt-dlp non e' nel PATH.\nInstallalo con:  winget install yt-dlp",
            )
            return
        save_config({"dest": dest, "threads": n})

        self.items.append({"url": url, "dest": dest, "n": n, "status": "pending"})
        self.write_log(f"+ in coda: {url}\n", "dim")
        self.url_var.set("")
        self.url_entry.focus()
        self.refresh_list()
        if self.paused and not self.running:
            self.write_log("coda in pausa: premi START per riprendere\n", "dim")
        else:
            self.process_next()

    def start_queue(self):
        self.paused = False
        self.abort_req = False
        for it in self.items:
            if it["status"] == "aborted":
                it["status"] = "pending"
        self.refresh_list()
        self.process_next()

    def remove_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        item = self.items[sel[0]]
        if item["status"] == "running":
            messagebox.showinfo("In corso", "Il download e' in corso: premi ABORT prima di rimuoverlo.")
            return
        self.items.remove(item)
        self.refresh_list()

    def clear_done(self):
        self.items = [i for i in self.items if i["status"] != "ok"]
        self.refresh_list()

    def process_next(self):
        if self.running:
            return
        item = next((i for i in self.items if i["status"] == "pending"), None)
        if item is None:
            if self.items:
                self.write_log("\n[OK] coda terminata\n", "dim")
            self.draw_bar()
            return

        os.makedirs(item["dest"], exist_ok=True)
        exe = shutil.which("yt-dlp")
        if not exe:
            item["status"] = "failed"
            self.write_log("\n[!!] yt-dlp non trovato nel PATH\n", "err")
            self.refresh_list()
            return
        cmd = [exe, "-N", str(item["n"]), "--newline", "-P", item["dest"], item["url"]]
        self.write_log("\n$ " + " ".join(cmd) + "\n", "dim")
        item["status"] = "running"
        self.percent = 0.0
        self.running = True
        self.abort_req = False
        self.stop_btn.set_enabled(True)
        self.refresh_list()
        self.tick()
        threading.Thread(target=self.run, args=(item, cmd), daemon=True).start()

    def run(self, item, cmd):
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        ok = False
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=flags,
            )
            for line in self.process.stdout:
                self.after(0, self.on_line, line)
            code = self.process.wait()
            ok = code == 0
            msg = "\n[OK] completato\n" if ok else f"\n[!!] terminato con codice {code}\n"
        except Exception as e:
            msg = f"\n[!!] errore: {e}\n"
        self.after(0, self.finish, item, ok, msg)

    def on_line(self, line):
        m = PCT_RE.search(line)
        if m and "[download]" in line:
            try:
                self.percent = min(100.0, float(m.group(1)))
            except ValueError:
                pass
        tag = "err" if line.lstrip().startswith("ERROR") else None
        self.write_log(line, tag)

    def finish(self, item, ok, msg):
        self.process = None
        self.running = False
        self.stop_btn.set_enabled(False)

        if self.abort_req:
            item["status"] = "aborted"
            self.paused = True
            self.abort_req = False
            self.write_log("\n[-] annullato, coda in pausa (START per riprendere)\n", "dim")
        else:
            item["status"] = "ok" if ok else "failed"
            self.write_log(msg, None if ok else "err")
            if ok:
                self.percent = 100.0

        self.refresh_list()
        if not self.paused:
            self.process_next()

    def stop(self):
        if self.process:
            self.abort_req = True
            self.process.terminate()


if __name__ == "__main__":
    App().mainloop()
