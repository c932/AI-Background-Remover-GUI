import os
import sys
import threading
import time
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

# --- [修复 1] 正确导入 DnDWrapper ---
try:
    from tkinterdnd2 import TkinterDnD, DND_ALL
    from tkinterdnd2 import DnDWrapper  # 直接导入 DnDWrapper 类
except ImportError:
    print("警告: 未安装 tkinterdnd2，拖拽功能将不可用。请运行: pip install tkinterdnd2")
    TkinterDnD = object
    DND_ALL = None


    class DnDWrapper:
        pass

# --- 设置本地模型路径 ---
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(os.path.abspath(sys.executable))
    local_model_path = os.path.join(os.path.dirname(sys.executable), "models")
    if not os.path.exists(local_model_path):
        local_model_path = os.path.join(base_path, "models")
else:
    local_model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

if os.path.exists(local_model_path):
    os.environ["U2NET_HOME"] = local_model_path


class AIBackgroundRemoverApp(ctk.CTk, DnDWrapper):
    def __init__(self):
        super().__init__()
        self.title("AI 智能抠图工具 Pro (极速稳定版 v3.3)")
        self.geometry("1200x750")
        ctk.set_appearance_mode("Dark")

        # --- 变量 ---
        self.original_image = None
        self.processed_image = None
        self.current_file_path = None
        self.current_model = "u2net"
        self.sessions = {}
        self.session_lock = threading.Lock()
        self.is_model_ready = False

        # --- UI ---
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._init_sidebar()
        self._init_main_area()

        # --- [修复 2] 正确初始化拖拽功能 ---
        if DND_ALL:
            try:
                # TkinterDnD._require 是实例方法，需要 (self, widget) 两个参数
                # 这里传入 self 两次，让主窗口既作为调用者也作为目标 widget
                self.TkdndVersion = TkinterDnD._require(self, self)

                self.drop_target_register(DND_ALL)
                self.dnd_bind('<<Drop>>', self._on_drop)
            except Exception as e:
                print(f"拖拽初始化失败: {e}")

        # --- 启动后台加载 ---
        self.status_label.configure(text="正在初始化 AI 引擎...")
        self.after(100, lambda: threading.Thread(target=self._preload_libraries, daemon=True).start())

    def _on_drop(self, event):
        file_path = event.data
        # Windows 下拖拽路径如果包含空格，会被 {} 包裹，需要去除
        if file_path.startswith('{') and file_path.endswith('}'):
            file_path = file_path[1:-1]

        # 简单处理：如果是多个文件，只取第一个
        if ' ' in file_path and not os.path.exists(file_path):
            parts = file_path.split(' ')
            if os.path.exists(parts[0]):
                file_path = parts[0]

        self.load_image(file_path)

    def _preload_libraries(self):
        try:
            import rembg
            import onnxruntime
            self._get_session("u2net")
            self.is_model_ready = True
            self.after(0, self._on_model_ready)
        except Exception as e:
            print(f"预加载警告: {e}")
            self.is_model_ready = True
            self.after(0, lambda: self.status_label.configure(text="初始化警告，但在运行中尝试修复"))

    def _on_model_ready(self):
        if self.original_image:
            self.btn_process.configure(state="normal")
            self.status_label.configure(text="准备就绪")
        else:
            self.status_label.configure(text="AI 引擎就绪，请导入或拖入图片")

    def _init_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(self.sidebar_frame, text="AI Remover Pro", font=ctk.CTkFont(size=22, weight="bold")).pack(
            pady=(30, 20))

        ctk.CTkLabel(self.sidebar_frame, text="第一步: 导入", text_color="gray").pack(anchor="w", padx=20, pady=(10, 0))
        self.btn_upload = ctk.CTkButton(self.sidebar_frame, text="📂 打开图片 (支持拖拽)", height=40,
                                        command=self.load_image)
        self.btn_upload.pack(padx=20, pady=10)

        ctk.CTkLabel(self.sidebar_frame, text="第二步: 算法设置", text_color="gray").pack(anchor="w", padx=20,
                                                                                          pady=(20, 0))
        self.model_var = ctk.StringVar(value="u2net (标准)")
        self.model_menu = ctk.CTkOptionMenu(self.sidebar_frame,
                                            values=["u2net (标准)", "isnet-general-use (高精度)",
                                                    "isnet-anime (动漫专用)"],
                                            command=self.change_model, variable=self.model_var)
        self.model_menu.pack(padx=20, pady=10)

        self.use_alpha_matting = ctk.BooleanVar(value=False)
        self.switch_matting = ctk.CTkSwitch(self.sidebar_frame, text="边缘精修 (Alpha Matting)",
                                            variable=self.use_alpha_matting, onvalue=True, offvalue=False)
        self.switch_matting.pack(padx=20, pady=10)

        self.tip_label = ctk.CTkLabel(self.sidebar_frame, text="💡 提示: 支持直接拖入图片",
                                      text_color="gray60", font=("Arial", 12))
        self.tip_label.pack(padx=20, pady=5)

        ctk.CTkLabel(self.sidebar_frame, text="第三步: 执行", text_color="gray").pack(anchor="w", padx=20, pady=(20, 0))
        self.btn_process = ctk.CTkButton(self.sidebar_frame, text="⚡ 开始抠图", height=40, fg_color="#106A43",
                                         state="disabled", command=self.start_processing)
        self.btn_process.pack(padx=20, pady=10)

        self.btn_save = ctk.CTkButton(self.sidebar_frame, text="💾 保存结果", height=40, fg_color="transparent",
                                      border_width=2, text_color=("gray10", "#DCE4EE"),
                                      state="disabled", command=self.save_image)
        self.btn_save.pack(padx=20, pady=10)

        self.status_label = ctk.CTkLabel(self.sidebar_frame, text="准备就绪", text_color="gray")
        self.status_label.pack(side="bottom", pady=20)

    def _init_main_area(self):
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(1, weight=1)

        self.label_orig = ctk.CTkLabel(self.main_frame, text="原始图片\n(拖拽图片到此处)", width=400, height=500,
                                       fg_color=("gray85", "gray20"), corner_radius=15)
        self.label_orig.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.label_result = ctk.CTkLabel(self.main_frame, text="处理结果", width=400, height=500,
                                         fg_color=("gray85", "gray20"), corner_radius=15)
        self.label_result.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        self.progressbar = ctk.CTkProgressBar(self.main_frame, mode="indeterminate", width=400)
        self.progressbar.grid(row=1, column=0, columnspan=2, pady=20)
        self.progressbar.grid_remove()

    def change_model(self, choice):
        map_name = {
            "u2net (标准)": "u2net",
            "isnet-general-use (高精度)": "isnet-general-use",
            "isnet-anime (动漫专用)": "isnet-anime"
        }
        new_model = map_name.get(choice, "u2net")
        if new_model != self.current_model:
            self.current_model = new_model
            self.status_label.configure(text=f"切换中: {new_model}")
            threading.Thread(target=self._get_session, args=(new_model,), daemon=True).start()

    def _get_session(self, model_name):
        with self.session_lock:
            from rembg import new_session
            if model_name not in self.sessions:
                if len(self.sessions) > 0:
                    self.sessions.clear()
                try:
                    self.after(0, lambda: self.status_label.configure(text=f"加载模型 {model_name}..."))
                    providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
                    session = new_session(model_name, providers=providers)
                    self.sessions[model_name] = session
                    self.after(0, lambda: self.status_label.configure(text=f"模型 {model_name} 就绪"))
                except Exception as e:
                    print(f"Model Init Error: {e}")
                    return None
            return self.sessions[model_name]

    def load_image(self, file_path=None):
        if not file_path:
            file_path = filedialog.askopenfilename(filetypes=[("Images", "*.jpg;*.png;*.webp;*.jpeg;*.bmp")])

        if file_path:
            valid_exts = ['.jpg', '.jpeg', '.png', '.webp', '.bmp']
            if not any(file_path.lower().endswith(ext) for ext in valid_exts):
                messagebox.showerror("错误", "不支持的文件格式")
                return

            try:
                self.current_file_path = file_path
                self.original_image = Image.open(file_path)
                self._display_image(self.original_image, self.label_orig)
                self.label_result.configure(image=None, text="等待处理...")
                self.processed_image = None

                if self.is_model_ready:
                    self.btn_process.configure(state="normal")
                    self.status_label.configure(text="准备就绪")
                else:
                    self.btn_process.configure(state="disabled")
                    self.status_label.configure(text="正在加载模型，请稍候...")

                self.btn_save.configure(state="disabled")
            except Exception as e:
                messagebox.showerror("错误", f"无法打开图片: {e}")

    def start_processing(self):
        if not self.original_image: return
        self.btn_process.configure(state="disabled")
        self.progressbar.grid()
        self.progressbar.start()
        self.status_label.configure(text="正在计算...")
        threading.Thread(target=self._process_thread, args=(self.current_model, self.use_alpha_matting.get())).start()

    def _process_thread(self, model_name, alpha_matting):
        start_t = time.time()
        try:
            from rembg import remove
            session = self._get_session(model_name)
            if not session: raise Exception("模型加载失败")
            res = remove(self.original_image, session=session, alpha_matting=alpha_matting,
                         alpha_matting_foreground_threshold=240, alpha_matting_background_threshold=10)
            self.processed_image = res
            self.after(0, lambda: self._success_callback(time.time() - start_t))
        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda: self._error_callback(err_msg))

    def _success_callback(self, elapsed):
        self._display_image(self.processed_image, self.label_result, is_result=True)
        self.status_label.configure(text=f"完成! 耗时 {elapsed:.2f}s")
        self.btn_save.configure(state="normal")
        self._reset_ui()

    def _error_callback(self, err_msg):
        messagebox.showerror("错误", f"处理出错: {err_msg}")
        self.status_label.configure(text="出错")
        self._reset_ui()

    def _reset_ui(self):
        self.progressbar.stop()
        self.progressbar.grid_remove()
        self.btn_process.configure(state="normal")

    def save_image(self):
        if self.processed_image:
            initial_file = "result.png"
            if self.current_file_path:
                base_name = os.path.basename(self.current_file_path)
                name, _ = os.path.splitext(base_name)
                initial_file = f"{name}_rmbg.png"

            path = filedialog.asksaveasfilename(
                defaultextension=".png",
                filetypes=[("PNG", "*.png")],
                initialfile=initial_file
            )
            if path:
                self.processed_image.save(path)

    def _create_checkerboard(self, w, h, cell_size=20):
        img = Image.new("RGB", (w, h), (200, 200, 200))
        pixels = img.load()
        for y in range(h):
            for x in range(w):
                if (x // cell_size + y // cell_size) % 2 == 0:
                    pixels[x, y] = (255, 255, 255)
        return img

    def _display_image(self, img, label, is_result=False):
        target_w, target_h = label.winfo_width(), label.winfo_height()
        if target_w < 50: target_w, target_h = 400, 500
        img_copy = img.copy()
        img_copy.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
        if is_result and img_copy.mode == 'RGBA':
            bg = self._create_checkerboard(img_copy.width, img_copy.height)
            bg.paste(img_copy, (0, 0), img_copy)
            final_img = bg
        else:
            final_img = img_copy
        ctk_img = ctk.CTkImage(light_image=final_img, dark_image=final_img, size=final_img.size)
        label.configure(image=ctk_img, text="")
        label._current_image = ctk_img


if __name__ == "__main__":
    app = AIBackgroundRemoverApp()
    app.mainloop()
