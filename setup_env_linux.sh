#!/bin/bash
echo "======================================================="
echo "Cài đặt môi trường ảo Python (.venv) cho Linux"
echo "======================================================="

# Create venv (Python 3)
python3 -m venv .venv

# Install requirements inside venv
source .venv/bin/activate
pip install -r requirements.txt

echo ""
echo "======================================================="
echo "Hoàn thành!"
echo "Môi trường của bạn đã sẵn sàng."
echo "Để sử dụng, hãy chạy lệnh: source .venv/bin/activate"
echo "======================================================="
