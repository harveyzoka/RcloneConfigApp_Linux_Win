import sys
import os

IS_WINDOWS = sys.platform == 'win32'
if not IS_WINDOWS:
    # Use native wayland if on Wayland to prevent XWayland's "Remote Desktop" screen sharing prompt
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "wayland"

import json
import shlex
import subprocess
import psutil
import shutil
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, 
    QCheckBox, QMessageBox, QInputDialog, QDialog, QLabel, QLineEdit, QComboBox
)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, QTimer
from reference_dialog import ReferenceDialog

IS_WINDOWS = sys.platform == 'win32'

def find_rclone():
    rclone_path = shutil.which("rclone")
    if rclone_path:
        return rclone_path
    return "C:\\rclone\\rclone.exe" if IS_WINDOWS else "rclone"

RCLONE_EXE = find_rclone()

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def get_settings_file():
    if IS_WINDOWS:
        config_root = os.environ.get("APPDATA") or os.path.expanduser("~")
        config_dir = os.path.join(config_root, "RcloneAutoMount")
        return os.path.join(config_dir, "settings.json")
    return os.path.join(get_base_dir(), "settings.json")

def get_log_file():
    return os.path.join(os.path.dirname(SETTINGS_FILE), "rclone_mount.log")

def rclone_exists():
    return os.path.exists(RCLONE_EXE) or shutil.which(RCLONE_EXE) is not None

def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

SETTINGS_FILE = get_settings_file()
LEGACY_SETTINGS_FILE = os.path.join(get_base_dir(), "settings.json")
LOG_FILE = get_log_file()

# Process Creation Flags for Windows
if IS_WINDOWS:
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
else:
    CREATE_NO_WINDOW = 0
    DETACHED_PROCESS = 0

class ConfigManager:
    @staticmethod
    def load():
        settings_file = SETTINGS_FILE
        if not os.path.exists(settings_file) and os.path.exists(LEGACY_SETTINGS_FILE):
            settings_file = LEGACY_SETTINGS_FILE

        if os.path.exists(settings_file):
            try:
                with open(settings_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {"mounts": []}

    @staticmethod
    def save(data):
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True, None
        except Exception as e:
            return False, str(e)


class StartupManager:
    @staticmethod
    def get_startup_vbs_path():
        startup_dir = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
        return os.path.join(startup_dir, "RcloneAutoMount.vbs")

    @staticmethod
    def get_startup_desktop_path():
        config_dir = os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))
        autostart_dir = os.path.join(config_dir, "autostart")
        os.makedirs(autostart_dir, exist_ok=True)
        return os.path.join(autostart_dir, "RcloneAutoMount.desktop")

    @staticmethod
    def update_startup_script(mounts):
        # We only create the startup script if there are auto_start mounts.
        app_path = os.path.abspath(sys.argv[0])
        is_exe = app_path.endswith('.exe') if IS_WINDOWS else not app_path.endswith('.py')
        
        has_auto = any(m.get("auto_start", False) for m in mounts)
        
        if IS_WINDOWS:
            vbs_path = StartupManager.get_startup_vbs_path()
            if has_auto:
                vbs_content = 'Set WshShell = CreateObject("WScript.Shell")\n'
                if is_exe:
                    vbs_content += f'WshShell.Run """{app_path}"" --startup", 0, False\n'
                else:
                    python_exe = sys.executable
                    vbs_content += f'WshShell.Run """{python_exe}"" ""{app_path}"" --startup", 0, False\n'
                with open(vbs_path, "w", encoding="utf-8") as f:
                    f.write(vbs_content)
            else:
                if os.path.exists(vbs_path):
                    os.remove(vbs_path)
        else:
            desktop_path = StartupManager.get_startup_desktop_path()
            if has_auto:
                cmd = f'"{app_path}" --startup' if is_exe else f'"{sys.executable}" "{app_path}" --startup'
                desktop_content = f"""[Desktop Entry]
Type=Application
Name=RcloneAutoMount
Exec={cmd}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""
                with open(desktop_path, "w", encoding="utf-8") as f:
                    f.write(desktop_content)
            else:
                if os.path.exists(desktop_path):
                    os.remove(desktop_path)


class MountManager:
    @staticmethod
    def get_rclone_remotes():
        if not rclone_exists():
            return []
        try:
            # Hide console for this command too
            kwargs = {}
            if IS_WINDOWS:
                kwargs['creationflags'] = CREATE_NO_WINDOW
            result = subprocess.run([RCLONE_EXE, "config", "dump"], capture_output=True, text=True, **kwargs)
            data = json.loads(result.stdout)
            return list(data.keys())
        except Exception as e:
            print("Error parsing rclone config", e)
            return []

    @staticmethod
    def get_active_mounts():
        active = {}
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = proc.info.get('name', '')
                if name and name.lower() in ('rclone.exe', 'rclone'):
                    cmdline = proc.info.get('cmdline', [])
                    if len(cmdline) >= 4 and cmdline[1] == 'mount':
                        remote = cmdline[2]
                        mountpoint = cmdline[3]
                        active[f"{remote}_{mountpoint}"] = proc.info['pid']
            except Exception as e:
                pass
        return active

    @staticmethod
    def start_mount(mount_cfg):
        remote = mount_cfg["remote"]
        mountpoint = os.path.expanduser(mount_cfg["mountpoint"])
        flags = mount_cfg.get("flags", "")
        
        if not IS_WINDOWS:
            # Rclone on Linux requires the mount folder to exist
            try:
                os.makedirs(mountpoint, exist_ok=True)
            except Exception as e:
                print(f"Lỗi tạo thư mục mount: {e}")
        
        cmd = [RCLONE_EXE, "mount", remote, mountpoint]
        if not IS_WINDOWS:
            cmd.append("--daemon")
            
        if flags:
            try:
                flag_list = shlex.split(flags, posix=not IS_WINDOWS)
            except ValueError as e:
                return False, f"Cờ mở rộng không hợp lệ: {e}", None
            if not IS_WINDOWS and "--network-mode" in flag_list:
                flag_list.remove("--network-mode")
            cmd.extend(flag_list)
             
        kwargs = {}
        log_handle = None
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            log_handle = open(LOG_FILE, "a", encoding="utf-8")
            log_handle.write("\n===== Rclone mount start =====\n")
            log_handle.write("Command: " + subprocess.list2cmdline(cmd) + "\n")
            log_handle.flush()
        except Exception:
            log_handle = None

        if IS_WINDOWS:
            kwargs['creationflags'] = CREATE_NO_WINDOW | DETACHED_PROCESS
            if log_handle:
                kwargs['stdout'] = log_handle
                kwargs['stderr'] = log_handle
        else:
            kwargs['start_new_session'] = True
            kwargs['stdout'] = log_handle or subprocess.DEVNULL
            kwargs['stderr'] = log_handle or subprocess.DEVNULL

        try:
            proc = subprocess.Popen(cmd, **kwargs)
            exit_code = proc.wait(timeout=2)
            error_tail = ""
            if log_handle:
                log_handle.flush()
                log_handle.close()
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    error_tail = f.read()[-3000:]
            except Exception:
                pass
            return False, f"Rclone thoát ngay với mã lỗi {exit_code}.\n\nLog: {LOG_FILE}\n\n{error_tail}", LOG_FILE
        except subprocess.TimeoutExpired:
            if log_handle:
                log_handle.flush()
                log_handle.close()
            return True, None, LOG_FILE
        except Exception as e:
            if log_handle:
                log_handle.close()
            return False, str(e), LOG_FILE

    @staticmethod
    def stop_mount(pid, mountpoint=None):
        if not IS_WINDOWS and mountpoint:
            try:
                os.system(f'fusermount3 -uz "{mountpoint}" || fusermount -uz "{mountpoint}"')
            except:
                pass
        else:
            try:
                p = psutil.Process(pid)
                p.kill()
            except:
                pass


class AddMountDialog(QDialog):
    def __init__(self, remotes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thêm cấu hình Mount")
        self.setWindowIcon(QIcon(get_resource_path('app_icon.ico')))
        self.resize(400, 200)
        self.remotes = remotes
        self.config = None
        self.parent_window = parent
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Chọn tài khoản Rclone (Remote):"))
        self.combo_remote = QComboBox()
        self.combo_remote.addItems(remotes)
        self.combo_remote.currentTextChanged.connect(self.on_remote_changed)
        layout.addWidget(self.combo_remote)
        
        if IS_WINDOWS:
            layout.addWidget(QLabel("Ô đĩa hoặc thư mục (VD: X: hoặc C:\\mnt):"))
            self.edit_mountpoint = QLineEdit()
            self.edit_mountpoint.setText("X:")
        else:
            layout.addWidget(QLabel("Thư mục (VD: /home/user/mnt/drive):"))
            self.edit_mountpoint = QLineEdit()
            # Gợi ý thư mục theo tên remote
            remote_name = remotes[0] if remotes else "drive"
            mnt_path = os.path.join(os.path.expanduser("~"), "mnt", remote_name)
            self.edit_mountpoint.setText(mnt_path)
        layout.addWidget(self.edit_mountpoint)
        
        layout.addWidget(QLabel("Cờ mở rộng (Gợi ý Cân Bằng có sẵn):"))
        self.edit_flags = QLineEdit()
        self.edit_flags.setText("--vfs-cache-mode full --vfs-cache-max-size 20G --vfs-cache-max-age 48h --buffer-size 128M --network-mode")
        layout.addWidget(self.edit_flags)
        
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Lưu")
        btn_save.clicked.connect(self.save_and_close)
        btn_cancel = QPushButton("Hủy")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)

    def on_remote_changed(self, remote_name):
        """Tự động cập nhật đường dẫn mount khi chọn remote khác"""
        if not IS_WINDOWS:
            mnt_path = os.path.join(os.path.expanduser("~"), "mnt", remote_name)
            self.edit_mountpoint.setText(mnt_path)
        
    def save_and_close(self):
        remote = self.combo_remote.currentText()
        if not remote.endswith(":"):
            remote += ":"
        
        mountpoint = self.edit_mountpoint.text().strip()
        flags = self.edit_flags.text().strip()
        
        if not mountpoint:
            QMessageBox.warning(self, "Lỗi", "Vui lòng nhập ổ đĩa/thư mục.")
            return
        
        # Kiểm tra trùng mountpoint với các mount đã có
        if self.parent_window:
            existing_mounts = self.parent_window.config_data.get("mounts", [])
            for m in existing_mounts:
                if os.path.expanduser(m["mountpoint"]) == os.path.expanduser(mountpoint):
                    QMessageBox.warning(self, "Lỗi", 
                        f"Thư mục '{mountpoint}' đã được sử dụng bởi remote '{m['remote']}'.\n"
                        f"Vui lòng chọn thư mục khác.")
                    return
            
        self.config = {
            "remote": remote,
            "mountpoint": mountpoint,
            "flags": flags,
            "auto_start": False
        }
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rclone Auto-Mount Manager")
        self.setWindowIcon(QIcon(get_resource_path('app_icon.ico')))
        self.resize(800, 500)
        
        self.config_data = ConfigManager.load()
        self.active_mounts = {}
        
        self.init_ui()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_active_status)
        self.refresh_timer.start(2000) # Check status every 2 seconds
        
        self.refresh_active_status()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Tools layout
        tools_layout = QHBoxLayout()
        btn_rclone_cfg = QPushButton("🔧 Mở cmd cấu hình Rclone gốc")
        btn_rclone_cfg.clicked.connect(self.open_rclone_config)
        tools_layout.addWidget(btn_rclone_cfg)
        
        btn_reference = QPushButton("📖 Bảng tra cứu các thông số")
        btn_reference.clicked.connect(self.open_reference)
        tools_layout.addWidget(btn_reference)
        
        tools_layout.addStretch()
        layout.addLayout(tools_layout)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Remote", "Ổ đĩa / Điểm Mount", "Tự chạy (Auto)", "Trạng thái", "Hành động"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)
        
        # Bottom Layout
        btn_layout = QHBoxLayout()
        btn_add = QPushButton("➕ Thêm cấu hình Mount")
        btn_add.clicked.connect(self.add_mount_config)
        btn_layout.addWidget(btn_add)
        btn_layout.addStretch()
        
        btn_del = QPushButton("❌ Xóa cấu hình đang chọn")
        btn_del.clicked.connect(self.delete_mount_config)
        btn_layout.addWidget(btn_del)
        
        layout.addLayout(btn_layout)
        
        self.populate_table()

    def populate_table(self):
        self.table.setRowCount(0)
        mounts = self.config_data.get("mounts", [])
        
        for idx, m in enumerate(mounts):
            self.table.insertRow(idx)
            self.table.setItem(idx, 0, QTableWidgetItem(m["remote"]))
            self.table.setItem(idx, 1, QTableWidgetItem(m["mountpoint"]))
            
            # Checkbox Auto Start
            chk_auto = QCheckBox()
            chk_auto.setChecked(m.get("auto_start", False))
            # Lambda trick to capture idx correctly
            chk_auto.stateChanged.connect(lambda state, i=idx: self.toggle_auto_start(i, state))
            
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk_auto)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(idx, 2, chk_widget)
            
            # Status Label
            lbl_status = QLabel("Kiểm tra...")
            lbl_status.setAlignment(Qt.AlignCenter)
            self.table.setCellWidget(idx, 3, lbl_status)
            
            # Action Button
            btn_action = QPushButton("Mount")
            btn_action.clicked.connect(lambda checked, i=idx: self.toggle_mount(i))
            self.table.setCellWidget(idx, 4, btn_action)

    def refresh_active_status(self):
        self.active_mounts = MountManager.get_active_mounts()
        mounts = self.config_data.get("mounts", [])
        
        for idx, m in enumerate(mounts):
            key = f"{m['remote']}_{m['mountpoint']}"
            is_running = key in self.active_mounts
            
            lbl_status = self.table.cellWidget(idx, 3)
            btn_action = self.table.cellWidget(idx, 4)
            
            if lbl_status and btn_action:
                if is_running:
                    lbl_status.setText("🟢 Đang chạy")
                    btn_action.setText("Dừng (Stop)")
                else:
                    lbl_status.setText("⚪ Tắt")
                    btn_action.setText("Khởi động (Mount)")

    def toggle_auto_start(self, idx, state):
        self.config_data["mounts"][idx]["auto_start"] = (state == Qt.Checked)
        ok, error = ConfigManager.save(self.config_data)
        if not ok:
            QMessageBox.critical(self, "Lỗi", f"Không lưu được cấu hình:\n{error}")
            return
        StartupManager.update_startup_script(self.config_data["mounts"])

    def toggle_mount(self, idx):
        m = self.config_data["mounts"][idx]
        key = f"{m['remote']}_{m['mountpoint']}"
        self.active_mounts = MountManager.get_active_mounts()
        
        if key in self.active_mounts:
            # Stop it
            pid = self.active_mounts[key]
            MountManager.stop_mount(pid, m['mountpoint'])
        else:
            # Start it
            if not rclone_exists():
                QMessageBox.critical(self, "Lỗi", f"Không tìm thấy rclone tại: {RCLONE_EXE}")
                return
            ok, error, log_file = MountManager.start_mount(m)
            if not ok:
                QMessageBox.critical(self, "Lỗi mount", error)
                return
            
        self.refresh_active_status()

    def add_mount_config(self):
        remotes = MountManager.get_rclone_remotes()
        # Clean remote names
        remotes = [r.replace(":", "") for r in remotes]
        if not remotes:
            QMessageBox.warning(self, "Lỗi", "Không tìm thấy remote rclone nào. Vui lòng cấu hình rclone trước.")
            return
        
        dlg = AddMountDialog(remotes, self)
        if dlg.exec_() == QDialog.Accepted and dlg.config:
            self.config_data["mounts"].append(dlg.config)
            ok, error = ConfigManager.save(self.config_data)
            if not ok:
                self.config_data["mounts"].pop()
                QMessageBox.critical(self, "Lỗi", f"Không lưu được cấu hình:\n{error}")
                return
            self.populate_table()

    def delete_mount_config(self):
        row = self.table.currentRow()
        if row >= 0:
            reply = QMessageBox.question(self, "Xóa", "Bạn có chắc muốn xóa cấu hình này?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                del self.config_data["mounts"][row]
                ok, error = ConfigManager.save(self.config_data)
                if not ok:
                    QMessageBox.critical(self, "Lỗi", f"Không lưu được cấu hình:\n{error}")
                    self.config_data = ConfigManager.load()
                    self.populate_table()
                    return
                StartupManager.update_startup_script(self.config_data["mounts"])
                self.populate_table()

    def open_rclone_config(self):
        if not rclone_exists():
            QMessageBox.critical(self, "Lỗi", f"Không tìm thấy rclone.")
            return
            
        if IS_WINDOWS:
            os.system(f'start cmd /c "{RCLONE_EXE} config"')
        else:
            terminals = [
                ('x-terminal-emulator', ['-e', RCLONE_EXE, 'config']),
                ('gnome-terminal', ['--', RCLONE_EXE, 'config']),
                ('konsole', ['-e', RCLONE_EXE, 'config']),
                ('xfce4-terminal', ['-x', RCLONE_EXE, 'config']),
                ('mate-terminal', ['--', RCLONE_EXE, 'config']),
                ('lxterminal', ['-e', RCLONE_EXE, 'config']),
                ('xterm', ['-e', RCLONE_EXE, 'config'])
            ]
            for term, args in terminals:
                if shutil.which(term):
                    try:
                        subprocess.Popen([term] + args)
                        return
                    except Exception as e:
                        print(f"Error launching {term}: {e}")
            QMessageBox.critical(self, "Lỗi", "Không tìm thấy phần mềm Terminal nào để mở rclone config.")
        
    def open_reference(self):
        dlg = ReferenceDialog(self)
        dlg.exec_()


def run_startup_mode():
    config = ConfigManager.load()
    mounts = config.get("mounts", [])
    active_mounts = MountManager.get_active_mounts()
    
    for m in mounts:
        if m.get("auto_start", False):
            key = f"{m['remote']}_{m['mountpoint']}"
            if key not in active_mounts:
                MountManager.start_mount(m)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--startup":
        run_startup_mode()
        sys.exit(0)
    else:
        app = QApplication(sys.argv)
        
        # Apply a clean, slight modern style
        app.setStyle("Fusion")
        
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())
