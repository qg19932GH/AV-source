import sys
import os
import shutil
import re
import subprocess
import stat
from PIL import Image

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QGridLayout, QLabel, QLineEdit, QPushButton, QCheckBox, 
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, 
    QTextEdit, QFileDialog, QGroupBox, QSplitter, QAbstractItemView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings

from parser import parse_filename
from scraper import JavBusScraper

class OrganizerWorker(QThread):
    # Signals to communicate with the GUI thread
    log_signal = pyqtSignal(str, str) # text, color (e.g., "white", "green", "red", "yellow")
    progress_signal = pyqtSignal(int) # percent
    status_signal = pyqtSignal(int, int, str) # row, column, text
    finished_signal = pyqtSignal(int, int) # success_count, fail_count

    def __init__(self, files, src_dir, dest_dir, options):
        super().__init__()
        self.files = files
        self.src_dir = src_dir
        self.dest_dir = dest_dir
        self.options = options # dict with keys: proxy, base_url, unmatched_folder, save_avatar, save_cover
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def set_folder_image_windows(self, folder_path, image_path):
        """Sets the folder preview logo on Windows via desktop.ini"""
        try:
            # 1. Destination for the logo inside the actor folder
            dest_img_path = os.path.join(folder_path, "folder.jpg")
            
            # Make sure destination folder exists
            os.makedirs(folder_path, exist_ok=True)
            
            # Copy and hide/system-protect existing permissions
            if os.path.exists(dest_img_path):
                # Temporarily remove hidden attribute to overwrite
                subprocess.run(["attrib", "-h", dest_img_path], capture_output=True, shell=True)
            shutil.copy2(image_path, dest_img_path)
            
            # 2. Write desktop.ini
            desktop_ini_path = os.path.join(folder_path, "desktop.ini")
            if os.path.exists(desktop_ini_path):
                subprocess.run(["attrib", "-h", "-s", desktop_ini_path], capture_output=True, shell=True)
                
            with open(desktop_ini_path, "w", encoding="gbk", errors="ignore") as f:
                f.write("[.ShellClassInfo]\n")
                f.write("ConfirmFileOp=0\n")
                f.write("[ViewState]\n")
                f.write("Mode=\n")
                f.write("Vid=\n")
                f.write("FolderType=Generic\n")
                f.write("Logo=folder.jpg\n")
                
            # 3. Apply windows attributes
            # desktop.ini must be Hidden and System
            subprocess.run(["attrib", "+h", "+s", desktop_ini_path], capture_output=True, shell=True)
            # folder.jpg should be Hidden
            subprocess.run(["attrib", "+h", dest_img_path], capture_output=True, shell=True)
            # The folder itself MUST be Read-only
            subprocess.run(["attrib", "+r", folder_path], capture_output=True, shell=True)
            return True
        except Exception as e:
            self.log_signal.emit(f"设置文件夹头像失败: {str(e)}", "yellow")
            return False

    def merge_avatars(self, image_paths, output_path):
        """Merges multiple avatar images into one side-by-side or grid layout"""
        if not image_paths:
            return False
        if len(image_paths) == 1:
            try:
                shutil.copy2(image_paths[0], output_path)
                return True
            except Exception as e:
                self.log_signal.emit(f"复制单个头像失败: {str(e)}", "red")
                return False
                
        try:
            images = []
            for p in image_paths:
                try:
                    img = Image.open(p)
                    images.append(img)
                except Exception as img_err:
                    self.log_signal.emit(f"打开头像图片失败 {p}: {str(img_err)}", "yellow")
                    
            if not images:
                return False
                
            # Normalize to square 150x150
            avatar_w, avatar_h = 150, 150
            resized_images = [img.resize((avatar_w, avatar_h), Image.Resampling.LANCZOS) for img in images]
            
            n = len(resized_images)
            if n == 2:
                # 2 images side-by-side (300 x 150)
                merged_img = Image.new('RGB', (avatar_w * 2, avatar_h))
                merged_img.paste(resized_images[0], (0, 0))
                merged_img.paste(resized_images[1], (avatar_w, 0))
            elif n == 3:
                # 3 images side-by-side (450 x 150)
                merged_img = Image.new('RGB', (avatar_w * 3, avatar_h))
                merged_img.paste(resized_images[0], (0, 0))
                merged_img.paste(resized_images[1], (avatar_w, 0))
                merged_img.paste(resized_images[2], (avatar_w * 2, 0))
            else:
                # 4 or more: 2x2 grid (300 x 300)
                merged_img = Image.new('RGB', (avatar_w * 2, avatar_h * 2))
                merged_img.paste(resized_images[0], (0, 0))
                merged_img.paste(resized_images[1], (avatar_w, 0))
                merged_img.paste(resized_images[2], (0, avatar_h))
                merged_img.paste(resized_images[3], (avatar_w, avatar_h))
                
            merged_img.save(output_path, 'JPEG')
            return True
        except Exception as e:
            self.log_signal.emit(f"合并头像失败: {str(e)}", "red")
            return False

    def run(self):
        success_count = 0
        fail_count = 0
        
        # Wrap the whole execution in try-except to prevent crashes on NAS/SMB
        try:
            scraper = JavBusScraper(
                base_url=self.options.get('base_url', 'https://www.javbus.com'),
                proxy=self.options.get('proxy', None),
                is_cancelled_cb=lambda: self._is_cancelled
            )
            
            # Temp dir inside destination for downloading avatars before merging
            temp_dir = os.path.join(self.dest_dir, ".temp_avatars")
            try:
                os.makedirs(temp_dir, exist_ok=True)
            except Exception as e:
                self.log_signal.emit(f"创建临时头像目录失败: {str(e)}", "red")
                
            total_files = len(self.files)
            self.log_signal.emit(f"开始处理，共 {total_files} 个文件...", "white")
            
            for idx, (row, filepath, code) in enumerate(self.files):
                if self._is_cancelled:
                    self.log_signal.emit("操作被用户取消", "yellow")
                    break
                    
                filename = os.path.basename(filepath)
                self.log_signal.emit(f"[{idx+1}/{total_files}] 正在查询: {filename} (编号: {code})", "white")
                self.status_signal.emit(row, 3, "查询中...")
                
                # If code is empty, handle as unmatched/failed immediately
                if not code or code.strip() == "":
                    try:
                        self.handle_unmatched(row, filepath, filename, temp_dir)
                    except Exception as e:
                        self.log_signal.emit(f"处理未匹配文件出错: {str(e)}", "red")
                    fail_count += 1
                    progress = int(((idx + 1) / total_files) * 100)
                    self.progress_signal.emit(progress)
                    continue
                    
                # Scrape movie details
                try:
                    details = scraper.scrape_movie_details(code)
                except Exception as e:
                    self.log_signal.emit(f"刮削番号 {code} 数据出错: {str(e)}", "red")
                    details = None
                    
                if details:
                    actresses_info = details.get('actresses', [])
                    actress_names = [a['name'] for a in actresses_info]
                    
                    if actress_names:
                        actual_combined = " & ".join(actress_names)
                        self.log_signal.emit(f"  -> 找到演员: {actual_combined}", "green")
                        
                        if len(actress_names) > 5:
                            combined_name = "多人共演"
                            self.log_signal.emit("  -> 演员人数大于 5 人，归类至多人共演文件夹", "yellow")
                        else:
                            combined_name = actual_combined
                            
                        self.status_signal.emit(row, 2, combined_name)
                        
                        # Target folder
                        target_folder = os.path.join(self.dest_dir, combined_name)
                        try:
                            os.makedirs(target_folder, exist_ok=True)
                        except Exception as e:
                            self.log_signal.emit(f"创建目标文件夹失败 ({combined_name}): {str(e)}，将作为未分类处理", "red")
                            try:
                                self.handle_unmatched(row, filepath, filename, temp_dir)
                            except Exception as ue:
                                self.log_signal.emit(f"移入未分类目录失败: {str(ue)}", "red")
                            fail_count += 1
                            progress = int(((idx + 1) / total_files) * 100)
                            self.progress_signal.emit(progress)
                            continue
                            
                        # Save avatar and set folder preview logo
                        has_preview = os.path.exists(os.path.join(target_folder, "folder.jpg"))
                        if self.options.get('save_avatar', True) and len(actress_names) <= 5 and not has_preview:
                            actor = actresses_info[0]
                            avatar_url = scraper.get_avatar_url(actor['url'])
                            if avatar_url:
                                ext = avatar_url.split('.')[-1].split('?')[0]
                                if ext not in ['jpg', 'jpeg', 'png', 'gif']:
                                    ext = 'jpg'
                                temp_avatar_path = os.path.join(temp_dir, f"{code}_0.{ext}")
                                self.log_signal.emit(f"  -> 正在下载首位演员 {actor['name']} 的头像...", "white")
                                if scraper.download_image(avatar_url, temp_avatar_path):
                                    self.set_folder_image_windows(target_folder, temp_avatar_path)
                                    
                        # Download cover image
                        if self.options.get('save_cover', False) and details.get('cover_url'):
                            cover_url = details['cover_url']
                            cover_ext = cover_url.split('.')[-1].split('?')[0]
                            if cover_ext not in ['jpg', 'jpeg', 'png']:
                                cover_ext = 'jpg'
                            cover_dest = os.path.join(target_folder, f"{code}-cover.{cover_ext}")
                            self.log_signal.emit("  -> 正在下载影片封面...", "white")
                            scraper.download_image(cover_url, cover_dest)
                            
                        # Move video file and all related files (subtitles, etc.)
                        self.move_files(filepath, target_folder)
                        self.status_signal.emit(row, 3, "整理成功")
                        success_count += 1
                    else:
                        # Movie found, but no actress listed (e.g., VR, solo/unknown)
                        self.log_signal.emit(f"  -> 未在页面找到演员名字，移动到未分类", "yellow")
                        try:
                            self.handle_unmatched(row, filepath, filename, temp_dir)
                        except Exception as e:
                            self.log_signal.emit(f"移动到未分类出错: {str(e)}", "red")
                        fail_count += 1
                else:
                    self.log_signal.emit(f"  -> 查询失败，未找到相关元数据", "red")
                    try:
                        self.handle_unmatched(row, filepath, filename, temp_dir)
                    except Exception as e:
                        self.log_signal.emit(f"移动到未分类出错: {str(e)}", "red")
                    fail_count += 1
                    
                progress = int(((idx + 1) / total_files) * 100)
                self.progress_signal.emit(progress)
                
            # Clean up temp avatars directory
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
        except Exception as outer_err:
            self.log_signal.emit(f"处理任务时发生严重异常: {str(outer_err)}", "red")
        finally:
            self.finished_signal.emit(success_count, fail_count)

    def handle_unmatched(self, row, filepath, filename, temp_dir):
        """Moves unmatched files to the designated 'Unclassified' folder"""
        unmatched_name = self.options.get('unmatched_folder', '未分类')
        unmatched_dir = os.path.join(self.dest_dir, unmatched_name)
        try:
            os.makedirs(unmatched_dir, exist_ok=True)
        except Exception as e:
            self.log_signal.emit(f"创建未分类文件夹失败: {str(e)}", "red")
            self.status_signal.emit(row, 3, "分类创建失败")
            return
            
        self.move_files(filepath, unmatched_dir)
        self.status_signal.emit(row, 3, f"未匹配 (已移至{unmatched_name})")

    def move_files(self, filepath, target_folder):
        """Moves a video file and any related files (subtitles/nfo) with the same base name"""
        try:
            src_dir = os.path.dirname(filepath)
            filename = os.path.basename(filepath)
            basename, _ = os.path.splitext(filename)
            
            # Find related files
            all_files = os.listdir(src_dir)
            files_to_move = [filename]
            
            for f in all_files:
                f_path = os.path.join(src_dir, f)
                if os.path.isfile(f_path) and f != filename:
                    f_base, _ = os.path.splitext(f)
                    # Match identical stem (e.g., "ABP-123.srt" matches "ABP-123.mp4")
                    if f_base == basename or f.startswith(basename + "."):
                        files_to_move.append(f)
            
            # Perform Move operations
            for f in files_to_move:
                src_file = os.path.join(src_dir, f)
                dest_file = os.path.join(target_folder, f)
                if os.path.exists(src_file):
                    if os.path.exists(dest_file):
                        self.log_signal.emit(f"  -> 文件已存在于目标文件夹，跳过: {f}", "yellow")
                    else:
                        shutil.move(src_file, dest_file)
                        self.log_signal.emit(f"  -> 已移动文件: {f}", "white")
        except Exception as e:
            self.log_signal.emit(f"移动文件时出错: {str(e)}", "red")


class AVOrganizerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.scanned_files = [] # list of (filepath, code)
        self.worker = None
        self.init_ui()
        self.load_settings()
        
    def init_ui(self):
        self.setWindowTitle("AV 视频自动整理工具")
        self.resize(1000, 700)
        
        # Dark Theme stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background-color: #121212;
            }
            QWidget {
                color: #e0e0e0;
                font-family: 'Segoe UI', 'Microsoft YaHei', Arial, sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 15px;
                font-weight: bold;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit {
                background-color: #2b2b2b;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                padding: 6px;
                color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid #bb86fc;
            }
            QPushButton {
                background-color: #bb86fc;
                color: #000000;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #d7b7fd;
            }
            QPushButton:pressed {
                background-color: #9a66d4;
            }
            QPushButton#secondaryBtn {
                background-color: #2b2b2b;
                color: #e0e0e0;
                border: 1px solid #3d3d3d;
            }
            QPushButton#secondaryBtn:hover {
                background-color: #3d3d3d;
            }
            QPushButton#actionBtn {
                background-color: #03dac6;
                color: #000000;
            }
            QPushButton#actionBtn:hover {
                background-color: #66fff6;
            }
            QPushButton#cancelBtn {
                background-color: #cf6679;
                color: #ffffff;
            }
            QPushButton#cancelBtn:hover {
                background-color: #ff99a8;
            }
            QTableWidget {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
                gridline-color: #2d2d2d;
                color: #e0e0e0;
            }
            QTableWidget::item:selected {
                background-color: #332940;
                color: #bb86fc;
            }
            QHeaderView::section {
                background-color: #2b2b2b;
                color: #ffffff;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #3d3d3d;
            }
            QProgressBar {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 4px;
                text-align: center;
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #bb86fc;
                border-radius: 4px;
            }
            QTextEdit {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                color: #b0b0b0;
            }
            QScrollBar:vertical {
                border: none;
                background: #1e1e1e;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #3d3d3d;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #bb86fc;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                border: none;
                background: #1e1e1e;
                height: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:horizontal {
                background: #3d3d3d;
                min-width: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #bb86fc;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                border: none;
                background: none;
                width: 0px;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
        """)

        # Main Widget and Splitter Layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Splitter to separate left control panel and right file table
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # --- LEFT PANEL: Settings & Configuration ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)
        
        # Group 1: Directories
        dir_group = QGroupBox("目录设置")
        dir_grid = QGridLayout(dir_group)
        dir_grid.setSpacing(10)
        
        dir_grid.addWidget(QLabel("视频源文件夹:"), 0, 0)
        self.src_edit = QLineEdit()
        dir_grid.addWidget(self.src_edit, 0, 1)
        self.src_btn = QPushButton("浏览")
        self.src_btn.setObjectName("secondaryBtn")
        self.src_btn.clicked.connect(self.browse_src)
        dir_grid.addWidget(self.src_btn, 0, 2)
        
        dir_grid.addWidget(QLabel("分类目的地:"), 1, 0)
        self.dest_edit = QLineEdit()
        dir_grid.addWidget(self.dest_edit, 1, 1)
        self.dest_btn = QPushButton("浏览")
        self.dest_btn.setObjectName("secondaryBtn")
        self.dest_btn.clicked.connect(self.browse_dest)
        dir_grid.addWidget(self.dest_btn, 1, 2)
        
        dir_grid.addWidget(QLabel("未分类文件夹名:"), 2, 0)
        self.unmatched_edit = QLineEdit("未分类")
        dir_grid.addWidget(self.unmatched_edit, 2, 1, 1, 2)
        
        left_layout.addWidget(dir_group)
        
        # Group 2: Scraping & Network Configuration
        net_group = QGroupBox("爬虫与网络设置")
        net_grid = QGridLayout(net_group)
        net_grid.setSpacing(10)
        
        net_grid.addWidget(QLabel("JavBus 地址:"), 0, 0)
        self.url_edit = QLineEdit("https://www.javbus.com")
        net_grid.addWidget(self.url_edit, 0, 1)
        
        net_grid.addWidget(QLabel("网络代理:"), 1, 0)
        self.proxy_edit = QLineEdit("127.0.0.1:10808")
        self.proxy_edit.setPlaceholderText("例如: 127.0.0.1:10808 (可选)")
        net_grid.addWidget(self.proxy_edit, 1, 1)
        
        self.save_avatar_cb = QCheckBox("下载演员头像并设为文件夹预览图")
        self.save_avatar_cb.setChecked(True)
        net_grid.addWidget(self.save_avatar_cb, 2, 0, 1, 2)
        
        self.save_cover_cb = QCheckBox("下载影片封面图到演员文件夹")
        self.save_cover_cb.setChecked(False)
        net_grid.addWidget(self.save_cover_cb, 3, 0, 1, 2)
        
        left_layout.addWidget(net_group)
        
        # Buttons Panel
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()
        
        self.scan_btn = QPushButton("第一步：扫描源文件夹")
        self.scan_btn.clicked.connect(self.scan_directory)
        btn_layout.addWidget(self.scan_btn)
        
        self.process_btn = QPushButton("第二步：开始查询与分类")
        self.process_btn.setObjectName("actionBtn")
        self.process_btn.clicked.connect(self.start_processing)
        btn_layout.addWidget(self.process_btn)
        
        self.cancel_btn = QPushButton("取消运行")
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_processing)
        btn_layout.addWidget(self.cancel_btn)
        
        left_layout.addLayout(btn_layout)
        splitter.addWidget(left_widget)
        
        # --- RIGHT PANEL: File Table & Logs ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        
        # Table of files
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["视频文件名", "识别番号 (双击可修改)", "匹配演员", "当前状态"])
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 200)
        right_layout.addWidget(self.table)
        
        # Log console
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setPlaceholderText("系统运行日志将在此处显示...")
        right_layout.addWidget(self.log_console)
        
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        right_layout.addWidget(self.progress_bar)
        
        splitter.addWidget(right_widget)
        
        # Set panel widths
        splitter.setSizes([320, 680])
        
        # Log initial message
        self.log("系统就绪。请选择源文件夹和目的地文件夹以开始。", "white")

    def log(self, text, color="white"):
        color_map = {
            "white": "#e0e0e0",
            "green": "#03dac6",  # bright cyan-green
            "red": "#cf6679",    # bright red-pink
            "yellow": "#ffb74d"  # orange-yellow
        }
        hex_color = color_map.get(color, "#e0e0e0")
        self.log_console.append(f'<span style="color: {hex_color};">{text}</span>')
        # Autoscroll
        self.log_console.verticalScrollBar().setValue(
            self.log_console.verticalScrollBar().maximum()
        )

    def browse_src(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择视频源文件夹")
        if dir_path:
            self.src_edit.setText(dir_path)

    def browse_dest(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择分类目的地")
        if dir_path:
            self.dest_edit.setText(dir_path)

    def scan_directory(self):
        src = self.src_edit.text().strip()
        if not src or not os.path.exists(src):
            self.log("错误: 视频源文件夹路径无效或不存在！", "red")
            return
            
        self.log("正在扫描文件夹...", "white")
        self.table.setRowCount(0)
        self.scanned_files = []
        
        # Supported extensions
        video_extensions = ('.mp4', '.mkv', '.avi', '.wmv', '.rmvb', '.flv', '.mov', '.ts')
        
        try:
            files = [f for f in os.listdir(src) if f.lower().endswith(video_extensions)]
            if not files:
                self.log("未在源文件夹中找到任何视频文件。", "yellow")
                return
                
            self.table.setRowCount(len(files))
            for idx, f in enumerate(files):
                filepath = os.path.join(src, f)
                # Parse code
                code = parse_filename(f)
                self.scanned_files.append((filepath, code))
                
                # Populate table
                # Filename
                item_name = QTableWidgetItem(f)
                item_name.setFlags(item_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(idx, 0, item_name)
                
                # Parsed Code (Editable)
                item_code = QTableWidgetItem(code)
                item_code.setFlags(item_code.flags() | Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(idx, 1, item_code)
                
                # Actress (Placeholder)
                item_actress = QTableWidgetItem("")
                item_actress.setFlags(item_actress.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(idx, 2, item_actress)
                
                # Status
                item_status = QTableWidgetItem("等待处理")
                item_status.setFlags(item_status.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(idx, 3, item_status)
                
            self.log(f"扫描完毕，共发现 {len(files)} 个视频文件。您可以双击识别的番号进行手动修改校对。", "green")
        except Exception as e:
            self.log(f"扫描文件夹时出错: {str(e)}", "red")

    def start_processing(self):
        # Validation
        src = self.src_edit.text().strip()
        dest = self.dest_edit.text().strip()
        
        if not src or not os.path.exists(src):
            self.log("错误: 视频源文件夹路径无效或不存在！", "red")
            return
        if not dest or not os.path.exists(dest):
            self.log("错误: 目的地文件夹路径无效或不存在！", "red")
            return
            
        # Get list from table (in case user modified the parsed codes)
        files_to_process = []
        for row in range(self.table.rowCount()):
            if row >= len(self.scanned_files):
                continue
            original_filepath = self.scanned_files[row][0]
            # Ensure the file still exists
            if not os.path.exists(original_filepath):
                self.log(f"文件已不存在: {os.path.basename(original_filepath)}，跳过", "yellow")
                self.update_table_item(row, 3, "文件不存在")
                continue
            code_item = self.table.item(row, 1)
            code = code_item.text().strip() if code_item else ""
            files_to_process.append((row, original_filepath, code))
            
        if not files_to_process:
            self.log("无待处理的视频文件。请先扫描源文件夹并确保视频列表非空。", "yellow")
            return
            
        # Disable inputs
        self.set_ui_enabled(False)
        
        # Prepare options
        options = {
            'proxy': self.proxy_edit.text().strip() or None,
            'base_url': self.url_edit.text().strip() or "https://www.javbus.com",
            'unmatched_folder': self.unmatched_edit.text().strip() or "未分类",
            'save_avatar': self.save_avatar_cb.isChecked(),
            'save_cover': self.save_cover_cb.isChecked()
        }
        
        # Start background worker thread
        self.worker = OrganizerWorker(files_to_process, src, dest, options)
        
        # Connect signals
        self.worker.log_signal.connect(self.log)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.status_signal.connect(self.update_table_item)
        self.worker.finished_signal.connect(self.processing_finished)
        
        self.progress_bar.setValue(0)
        self.worker.start()

    def update_table_item(self, row, col, text):
        item = self.table.item(row, col)
        if item:
            item.setText(text)
        else:
            new_item = QTableWidgetItem(text)
            new_item.setFlags(new_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, col, new_item)

    def cancel_processing(self):
        if self.worker and self.worker.isRunning():
            self.log("正在请求取消运行...", "yellow")
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)

    def processing_finished(self, success, fail):
        self.log(f"任务完成！成功整理: {success} 个，失败/未分类: {fail} 个。", "green")
        self.set_ui_enabled(True)
        self.worker = None

    def set_ui_enabled(self, enabled):
        self.src_btn.setEnabled(enabled)
        self.dest_btn.setEnabled(enabled)
        self.src_edit.setEnabled(enabled)
        self.dest_edit.setEnabled(enabled)
        self.unmatched_edit.setEnabled(enabled)
        self.url_edit.setEnabled(enabled)
        self.proxy_edit.setEnabled(enabled)
        self.save_avatar_cb.setEnabled(enabled)
        self.save_cover_cb.setEnabled(enabled)
        self.scan_btn.setEnabled(enabled)
        self.process_btn.setEnabled(enabled)
        self.cancel_btn.setEnabled(not enabled)
        
        # Allow editing codes in table only when not running
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item:
                if enabled:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    
    def load_settings(self):
        settings = QSettings("AV_Organizer", "Settings")
        self.src_edit.setText(settings.value("src_dir", ""))
        self.dest_edit.setText(settings.value("dest_dir", ""))
        self.unmatched_edit.setText(settings.value("unmatched_folder", "未分类"))
        self.url_edit.setText(settings.value("base_url", "https://www.javbus.com"))
        self.proxy_edit.setText(settings.value("proxy", "127.0.0.1:10808"))
        
        save_avatar = settings.value("save_avatar", "true") == "true"
        self.save_avatar_cb.setChecked(save_avatar)
        
        save_cover = settings.value("save_cover", "false") == "true"
        self.save_cover_cb.setChecked(save_cover)

    def closeEvent(self, event):
        settings = QSettings("AV_Organizer", "Settings")
        settings.setValue("src_dir", self.src_edit.text().strip())
        settings.setValue("dest_dir", self.dest_edit.text().strip())
        settings.setValue("unmatched_folder", self.unmatched_edit.text().strip())
        settings.setValue("base_url", self.url_edit.text().strip())
        settings.setValue("proxy", self.proxy_edit.text().strip())
        settings.setValue("save_avatar", "true" if self.save_avatar_cb.isChecked() else "false")
        settings.setValue("save_cover", "true" if self.save_cover_cb.isChecked() else "false")
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = AVOrganizerApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
