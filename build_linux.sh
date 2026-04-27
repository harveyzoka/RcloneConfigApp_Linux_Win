#!/bin/bash
echo "======================================================="
echo "Building Rclone Auto-Mount Manager Executable (Linux)"
echo "======================================================="

# Make sure we are in the venv
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Lưu ý: Bạn chưa kích hoạt môi trường ảo."
    echo "Đang thử tự động kích hoạt .venv..."
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    else
        echo "Lỗi: Không tìm thấy .venv. Vui lòng chạy setup_env_linux.sh trước."
        exit 1
    fi
fi

# Run pyinstaller
# Note the use of colon `:` instead of semicolon `;` for --add-data on Linux
pyinstaller --noconfirm --noconsole --onedir --windowed --add-data="app_icon.ico:." --name="RcloneAutoMount_Linux" main.py

echo ""
echo "======================================================="
echo "Build Complete! Executable is located in the 'dist/RcloneAutoMount' folder."
echo "======================================================="
