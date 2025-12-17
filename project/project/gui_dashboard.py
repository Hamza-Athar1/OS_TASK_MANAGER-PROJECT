#!/usr/bin/env python3
import psutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import socket
import datetime
import os
import random
import subprocess
import time
from collections import deque

# ---------- Helper Functions ----------

def get_history_file():
    """Return path of available shell history file (bash or zsh), or None."""
    bash_hist = os.path.expanduser("~/.bash_history")
    zsh_hist = os.path.expanduser("~/.zsh_history")

    if os.path.exists(bash_hist):
        return bash_hist
    if os.path.exists(zsh_hist):
        return zsh_hist
    return None

def get_ip_address():
    try:
        hostname = socket.gethostname()
        return socket.gethostbyname(hostname)
    except Exception:
        return "Unknown"

def get_disk_usage():
    du = psutil.disk_usage('/')
    used_gb = du.used // (1024 ** 3)
    total_gb = du.total // (1024 ** 3)
    percent = du.percent
    return used_gb, total_gb, percent

def get_study_stats():
    """Read shell history (bash or zsh) and estimate study/terminal usage."""
    history_file = get_history_file()
    if not history_file:
        return ("History file not found", 0, [])

    try:
        with open(history_file, "r", errors="ignore") as f:
            lines = [l.strip() for l in f if l.strip()]
    except Exception:
        return ("Error reading history", 0, [])

    total_cmds = len(lines)

    freq = {}
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        cmd = parts[0]
        freq[cmd] = freq.get(cmd, 0) + 1

    top_cmds = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:3]
    top_cmd_names = [f"{c} ({n})" for c, n in top_cmds]

    return ("OK", total_cmds, top_cmd_names)

def get_security_info():
    """
    Check failed login attempts.

    1) If /var/log/auth.log exists -> use it.
    2) Otherwise fall back to journalctl.
    """
    auth_log = "/var/log/auth.log"

    # ---- Case 1: auth.log file available ----
    if os.path.exists(auth_log):
        try:
            result = subprocess.run(
                ["grep", "-c", "Failed password", auth_log],
                capture_output=True,
                text=True
            )
            if result.returncode not in (0, 1):
                return "Error reading auth.log", 0
            count = int(result.stdout.strip() or 0)
            return "OK", count
        except Exception:
            return "Error parsing auth.log", 0

    # ---- Case 2: use journalctl ----
    try:
        cmd = "journalctl -p 3 -xb | grep -c 'Failed password'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode not in (0, 1):
            return "Error reading journal", 0
        count_str = result.stdout.strip()
        count = int(count_str) if count_str else 0
        return "OK", count
    except Exception:
        return "No auth data available", 0

def get_safety_check():
    """Look for dangerous commands in recent shell history (bash or zsh)."""
    history_file = get_history_file()
    if not history_file:
        return "History file not found"

    dangerous_keywords = [
        "rm -rf /",
        "mkfs",
        ":(){ :|:& };:",
        "chmod 777",
        "dd if=",
    ]

    try:
        with open(history_file, "r", errors="ignore") as f:
            lines = [l.strip() for l in f if l.strip()]
    except Exception:
        return "Error reading history"

    recent = lines[-80:]  # last 80 commands
    for line in recent:
        for bad in dangerous_keywords:
            if bad in line:
                return f"WARNING: Dangerous command found -> {bad}"

    return "No extremely dangerous command found"

def calculate_health_score(cpu_percent, ram_percent, disk_percent, failed_logins):
    """Return approximate health score out of 100."""
    score = 100

    # CPU / RAM / Disk penalties
    score -= int(cpu_percent / 2)       # up to -50
    score -= int(ram_percent / 3)       # up to -33
    score -= int(disk_percent / 4)      # up to -25

    # Security penalty
    if failed_logins > 0:
        score -= min(20, failed_logins * 2)

    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return score

def command_of_the_day():
    commands = [
        ("htop", "Interactive process viewer"),
        ("ss -tulnp", "Show listening ports and processes"),
        ("nmap -sV <target>", "Scan open ports & service versions"),
        ("journalctl -p 3 -xb", "View recent critical system logs"),
        ("nc -lvnp 4444", "Start a simple TCP listener (for testing)"),
        ("rsync -av src/ dest/", "Efficient directory backup/sync"),
    ]
    return random.choice(commands)

# ---------- GUI Application ----------

class TaskStudyManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Kali Smart System & Study Assistant Manager")
        self.geometry("1000x650")
        self.configure(bg="#111111")

        # ----- Style (dark-ish theme) -----
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("Dark.TLabelframe", background="#202020", foreground="#ffffff")
        style.configure("Dark.TLabelframe.Label", background="#202020", foreground="#ffffff")
        style.configure("Dark.TLabel", background="#202020", foreground="#ffffff")
        style.configure("Dark.TButton", background="#303030", foreground="#ffffff")
        style.map("Dark.TButton",
                  background=[("active", "#505050")])

        # ----- Performance history (for graphs) -----
        self.history_len = 60  # ~60 samples (~60 seconds if refresh 1s)
        self.cpu_history = deque([0]*self.history_len, maxlen=self.history_len)
        self.ram_history = deque([0]*self.history_len, maxlen=self.history_len)
        self.net_down_history = deque([0]*self.history_len, maxlen=self.history_len)
        self.net_up_history = deque([0]*self.history_len, maxlen=self.history_len)

        self.last_net = psutil.net_io_counters()
        self.last_net_time = time.time()
        self.net_down = 0.0
        self.net_up = 0.0

        # Create all sections
        self.create_system_info_frame(style)
        self.create_graphs_frame(style)
        self.create_process_frame(style)
        self.create_panels_frame(style)
        self.create_bottom_actions(style)

        # First data load
        self.refresh_all()

        # Auto-refresh every 1.5 seconds
        self.refresh_ms = 1500
        self.after(self.refresh_ms, self.auto_refresh)

    # ----- Top: System Info -----
    def create_system_info_frame(self, style):
        frame = ttk.LabelFrame(self, text="System Status", style="Dark.TLabelframe")
        frame.pack(fill="x", padx=10, pady=5)

        self.cpu_label = ttk.Label(frame, text="CPU: ", style="Dark.TLabel")
        self.ram_label = ttk.Label(frame, text="RAM: ", style="Dark.TLabel")
        self.disk_label = ttk.Label(frame, text="Disk: ", style="Dark.TLabel")
        self.uptime_label = ttk.Label(frame, text="Uptime: ", style="Dark.TLabel")
        self.ip_label = ttk.Label(frame, text="IP: ", style="Dark.TLabel")

        self.cpu_label.grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.ram_label.grid(row=0, column=1, padx=5, pady=2, sticky="w")
        self.disk_label.grid(row=0, column=2, padx=5, pady=2, sticky="w")
        self.uptime_label.grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.ip_label.grid(row=1, column=1, padx=5, pady=2, sticky="w")

    # ----- Live Graphs -----
    def create_graphs_frame(self, style):
        frame = ttk.LabelFrame(self, text="Live Performance Graphs", style="Dark.TLabelframe")
        frame.pack(fill="x", padx=10, pady=5)

        W, H = 300, 150

        self.cpu_canvas = tk.Canvas(frame, width=W, height=H, bg="#101010",
                                    highlightthickness=1, highlightbackground="#444444")
        self.ram_canvas = tk.Canvas(frame, width=W, height=H, bg="#101010",
                                    highlightthickness=1, highlightbackground="#444444")
        self.net_canvas = tk.Canvas(frame, width=W*1.4, height=H, bg="#101010",
                                    highlightthickness=1, highlightbackground="#444444")

        self.cpu_canvas.grid(row=0, column=0, padx=5, pady=5)
        self.ram_canvas.grid(row=0, column=1, padx=5, pady=5)
        self.net_canvas.grid(row=0, column=2, padx=5, pady=5)

    # ----- Middle: Process Table -----
    def create_process_frame(self, style):
        frame = ttk.LabelFrame(self, text="Running Processes (like Task Manager)", style="Dark.TLabelframe")
        frame.pack(fill="both", expand=True, padx=10, pady=5)

        columns = ("pid", "name", "cpu", "memory")
        self.proc_tree = ttk.Treeview(frame, columns=columns, show="headings", height=10)
        self.proc_tree.heading("pid", text="PID")
        self.proc_tree.heading("name", text="Name")
        self.proc_tree.heading("cpu", text="CPU %")
        self.proc_tree.heading("memory", text="Memory %")

        self.proc_tree.column("pid", width=70)
        self.proc_tree.column("name", width=260)
        self.proc_tree.column("cpu", width=70)
        self.proc_tree.column("memory", width=80)

        # row color tags based on CPU usage (whole row changes)
        self.proc_tree.tag_configure("cpu_low", background="#001a00", foreground="#e0ffe0")     # safe (greenish)
        self.proc_tree.tag_configure("cpu_mid", background="#332200", foreground="#ffeb99")     # warning (orange)
        self.proc_tree.tag_configure("cpu_high", background="#330000", foreground="#ff9999")    # critical (red)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.proc_tree.yview)
        self.proc_tree.configure(yscroll=vsb.set)

        self.proc_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ----- Right Panel: Study + Security + Health -----
    def create_panels_frame(self, style):
        frame = ttk.LabelFrame(self, text="Study & Security Assistant", style="Dark.TLabelframe")
        frame.pack(fill="x", padx=10, pady=5)

        # Study tracker
        self.study_label = ttk.Label(frame, text="Study Tracker: ", style="Dark.TLabel")
        self.study_label.grid(row=0, column=0, sticky="w", padx=5, pady=2)

        # Safety checker
        self.safety_label = ttk.Label(frame, text="Safety Check: ", style="Dark.TLabel")
        self.safety_label.grid(row=1, column=0, sticky="w", padx=5, pady=2)

        # Security panel (failed logins)
        self.security_label = ttk.Label(frame, text="Security Panel: ", style="Dark.TLabel")
        self.security_label.grid(row=2, column=0, sticky="w", padx=5, pady=2)

        # Health score
        self.health_label = ttk.Label(frame, text="System Health Score: ", style="Dark.TLabel")
        self.health_label.grid(row=3, column=0, sticky="w", padx=5, pady=2)

        # Command of the day
        self.cmd_day_label = ttk.Label(frame, text="Command of the Day: ", style="Dark.TLabel")
        self.cmd_day_label.grid(row=4, column=0, sticky="w", padx=5, pady=2)

        self.tip_day_label = ttk.Label(frame, text="Tip: ", style="Dark.TLabel")
        self.tip_day_label.grid(row=5, column=0, sticky="w", padx=5, pady=2)

    # ----- Bottom Buttons -----
    def create_bottom_actions(self, style):
        frame = ttk.Frame(self, style="Dark.TFrame")
        frame.pack(fill="x", padx=10, pady=5)

        refresh_btn = ttk.Button(frame, text="Refresh", command=self.refresh_all, style="Dark.TButton")
        refresh_btn.pack(side="left", padx=5)

        kill_btn = ttk.Button(frame, text="End Selected Process", command=self.kill_selected_process, style="Dark.TButton")
        kill_btn.pack(side="left", padx=5)

        export_btn = ttk.Button(frame, text="Export Report", command=self.export_report, style="Dark.TButton")
        export_btn.pack(side="left", padx=5)

        backup_btn = ttk.Button(frame, text="Backup Projects Folder", command=self.backup_projects, style="Dark.TButton")
        backup_btn.pack(side="left", padx=5)

        exit_btn = ttk.Button(frame, text="Exit", command=self.destroy, style="Dark.TButton")
        exit_btn.pack(side="right", padx=5)

    # ----- Data Updates -----
    def refresh_all(self):
        self.update_system_info()
        self.populate_processes()
        self.update_panels()
        self.update_graphs()

    def auto_refresh(self):
        self.refresh_all()
        self.after(self.refresh_ms, self.auto_refresh)

    def _color_for_usage(self, value):
        """Return green / orange / red based on percentage."""
        if value < 50:
            return "#00cc66"   # green
        elif value < 80:
            return "#ff9900"   # orange
        else:
            return "#ff3333"   # red

    def update_system_info(self):
        # CPU
        cpu = psutil.cpu_percent(interval=0.2)

        # RAM
        ram = psutil.virtual_memory()
        ram_text = f"{ram.used // (1024 ** 2)}MiB / {ram.total // (1024 ** 2)}MiB ({ram.percent}%)"

        # Disk
        used_gb, total_gb, percent = get_disk_usage()

        # Uptime
        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime_delta = datetime.datetime.now() - boot_time
        uptime_str = str(uptime_delta).split(".")[0]

        # IP
        ip = get_ip_address()

        # Network rates (KB/s)
        now = time.time()
        counters = psutil.net_io_counters()
        dt = now - self.last_net_time if now > self.last_net_time else 1.0

        self.net_down = (counters.bytes_recv - self.last_net.bytes_recv) / dt / 1024.0
        self.net_up = (counters.bytes_sent - self.last_net.bytes_sent) / dt / 1024.0

        self.last_net = counters
        self.last_net_time = now

        # Update labels
        self.cpu_label.config(text=f"CPU: {cpu:.1f}%")
        self.ram_label.config(text=f"RAM: {ram_text}")
        self.disk_label.config(text=f"Disk: {used_gb}G / {total_gb}G ({percent}%)")
        self.uptime_label.config(text=f"Uptime: {uptime_str}")
        self.ip_label.config(text=f"IP: {ip}")

        # Color coding
        self.cpu_label.config(foreground=self._color_for_usage(cpu))
        self.ram_label.config(foreground=self._color_for_usage(ram.percent))

        # Store latest values for health score & graphs
        self.latest_cpu = cpu
        self.latest_ram = ram.percent
        self.latest_disk = percent

        # Push into history deques
        self.cpu_history.append(cpu)
        self.ram_history.append(ram.percent)
        self.net_down_history.append(self.net_down)
        self.net_up_history.append(self.net_up)

    def populate_processes(self):
        # Clear old rows
        for row in self.proc_tree.get_children():
            self.proc_tree.delete(row)

        # Populate table with colored rows
        for proc in psutil.process_iter(attrs=["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                pid = proc.info["pid"]
                name = proc.info["name"]
                cpu = proc.info["cpu_percent"]
                mem = proc.info["memory_percent"]

                if cpu is None:
                    cpu = 0.0
                if mem is None:
                    mem = 0.0

                # decide tag based on CPU usage (whole row color)
                if cpu < 20:
                    tag = "cpu_low"
                elif cpu < 50:
                    tag = "cpu_mid"
                else:
                    tag = "cpu_high"

                self.proc_tree.insert(
                    "", "end",
                    values=(pid, name, f"{cpu:.1f}", f"{mem:.1f}"),
                    tags=(tag,)
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def update_panels(self):
        # Study tracker
        status, total_cmds, top_cmds = get_study_stats()
        if status != "OK":
            self.study_label.config(text=f"Study Tracker: {status}")
        else:
            top_text = ", ".join(top_cmds)
            self.study_label.config(
                text=f"Study Tracker: {total_cmds} commands used, top: {top_text}"
            )

        # Safety checker
        safety_msg = get_safety_check()
        self.safety_label.config(text=f"Safety Check: {safety_msg}")

        # Security panel
        sec_status, failed = get_security_info()
        if sec_status != "OK":
            self.security_label.config(text=f"Security Panel: {sec_status}")
            failed = 0   # don't punish score if log missing
        else:
            self.security_label.config(
                text=f"Security Panel: Failed logins today = {failed}"
            )

        # Health score
        health = calculate_health_score(
            getattr(self, "latest_cpu", 0),
            getattr(self, "latest_ram", 0),
            getattr(self, "latest_disk", 0),
            failed,
        )
        self.health_label.config(text=f"System Health Score: {health} / 100")
        self.health_label.config(foreground=self._color_for_usage(100 - health))  # low health -> red

        # Command of the day
        cmd, desc = command_of_the_day()
        self.cmd_day_label.config(text=f"Command of the Day: {cmd}")
        self.tip_day_label.config(text=f"Tip: {desc}")

    # ----- Graph Drawing -----
    def _draw_line_graph(self, canvas, data, max_value, line_color, title, unit="%", extra_text=""):
        W = int(canvas["width"])
        H = int(canvas["height"])
        canvas.delete("all")

        # Background grid
        canvas.create_rectangle(0, 0, W, H, fill="#101010", outline="#444444")
        for i in range(1, 4):
            y = i * H / 4
            canvas.create_line(0, y, W, y, fill="#222222")

        # Title
        canvas.create_text(10, 10, anchor="nw", fill="#ffffff",
                           text=f"{title}: {data[-1]:.1f}{unit} {extra_text}")

        if len(data) < 2:
            return

        # Normalize data
        max_val = max(max_value, max(data) if data else 0.0, 1.0)
        scale_y = (H - 25) / max_val
        step_x = W / (len(data) - 1)

        points = []
        for i, value in enumerate(data):
            x = i * step_x
            y = H - 10 - (value * scale_y)
            points.append((x, y))

        # Draw line
        for i in range(1, len(points)):
            x1, y1 = points[i-1]
            x2, y2 = points[i]
            canvas.create_line(x1, y1, x2, y2, fill=line_color, width=2)

    def update_graphs(self):
        # CPU graph
        self._draw_line_graph(
            self.cpu_canvas,
            list(self.cpu_history),
            max_value=100.0,
            line_color="#00cc66",
            title="CPU"
        )

        # RAM graph
        self._draw_line_graph(
            self.ram_canvas,
            list(self.ram_history),
            max_value=100.0,
            line_color="#cc66ff",
            title="RAM"
        )

        # Network graph (down + up)
        W = int(self.net_canvas["width"])
        H = int(self.net_canvas["height"])
        self.net_canvas.delete("all")
        self.net_canvas.create_rectangle(0, 0, W, H, fill="#101010", outline="#444444")
        for i in range(1, 4):
            y = i * H / 4
            self.net_canvas.create_line(0, y, W, y, fill="#222222")

        # Determine max scale
        data_down = list(self.net_down_history)
        data_up = list(self.net_up_history)
        all_vals = data_down + data_up
        max_val = max(all_vals) if all_vals else 0.0
        max_val = max(max_val, 1.0)
        scale_y = (H - 25) / max_val
        step_x = W / (len(data_down) - 1 if len(data_down) > 1 else 1)

        # Draw download line (blue)
        points = []
        for i, value in enumerate(data_down):
            x = i * step_x
            y = H - 10 - (value * scale_y)
            points.append((x, y))
        for i in range(1, len(points)):
            x1, y1 = points[i-1]
            x2, y2 = points[i]
            self.net_canvas.create_line(x1, y1, x2, y2, fill="#3399ff", width=2)

        # Draw upload line (orange)
        points = []
        for i, value in enumerate(data_up):
            x = i * step_x
            y = H - 10 - (value * scale_y)
            points.append((x, y))
        for i in range(1, len(points)):
            x1, y1 = points[i-1]
            x2, y2 = points[i]
            self.net_canvas.create_line(x1, y1, x2, y2, fill="#ff9933", width=2)

        # Legend + current rates
        text = f"Net Down: {self.net_down:.1f} KB/s | Up: {self.net_up:.1f} KB/s"
        self.net_canvas.create_text(10, 10, anchor="nw", fill="#ffffff", text=text)
        self.net_canvas.create_text(W-10, H-10, anchor="se", fill="#3399ff",
                                    text="Blue=Down, Orange=Up")

    # ----- Button Handlers -----
    def kill_selected_process(self):
        selected = self.proc_tree.selection()
        if not selected:
            messagebox.showwarning("No selection", "Please select a process first.")
            return
        pid = int(self.proc_tree.item(selected[0])["values"][0])
        try:
            p = psutil.Process(pid)
            name = p.name()
            if messagebox.askyesno("Confirm", f"End process {name} (PID {pid})?"):
                p.terminate()
                messagebox.showinfo("Done", f"Process {name} terminated.")
                self.populate_processes()
        except psutil.NoSuchProcess:
            messagebox.showerror("Error", "Process no longer exists.")
        except psutil.AccessDenied:
            messagebox.showerror("Error", "Access denied. Try running as root.")

    def export_report(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")],
            title="Save System Report"
        )
        if not filename:
            return

        try:
            with open(filename, "w") as f:
                f.write("Kali Smart System & Study Assistant Report\n")
                f.write("=" * 60 + "\n\n")
                f.write(self.cpu_label.cget("text") + "\n")
                f.write(self.ram_label.cget("text") + "\n")
                f.write(self.disk_label.cget("text") + "\n")
                f.write(self.uptime_label.cget("text") + "\n")
                f.write(self.ip_label.cget("text") + "\n\n")

                f.write(self.study_label.cget("text") + "\n")
                f.write(self.safety_label.cget("text") + "\n")
                f.write(self.security_label.cget("text") + "\n")
                f.write(self.health_label.cget("text") + "\n\n")

                f.write(self.cmd_day_label.cget("text") + "\n")
                f.write(self.tip_day_label.cget("text") + "\n\n")

                f.write("Top Processes:\n")
                for row in self.proc_tree.get_children():
                    vals = self.proc_tree.item(row)["values"]
                    line = f"PID {vals[0]} | {vals[1]} | CPU {vals[2]}% | MEM {vals[3]}%\n"
                    f.write(line)

            messagebox.showinfo("Saved", f"Report saved to {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save report: {e}")

    def backup_projects(self):
        home = os.path.expanduser("~")
        src = os.path.join(home, "Projects")
        if not os.path.exists(src):
            messagebox.showwarning(
                "Not Found",
                f"'Projects' folder not found in {home}. Create it first."
            )
            return

        backup_dir = filedialog.askdirectory(
            title="Select folder where backup should be saved"
        )
        if not backup_dir:
            return

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(backup_dir, f"projects_backup_{timestamp}.tar.gz")
        try:
            subprocess.run(["tar", "-czf", dest, "-C", home, "Projects"], check=True)
            messagebox.showinfo("Backup Complete", f"Backup saved to:\n{dest}")
        except Exception as e:
            messagebox.showerror("Error", f"Backup failed: {e}")


if __name__ == "__main__":
    app = TaskStudyManager()
    app.mainloop()
