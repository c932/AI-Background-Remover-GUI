import os
import sys
import threading
import time
# --- 1. 仅导入轻量级 GUI 库 ---
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

# --- 2. 设置本地模型路径 ---
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(os.path.abspath(sys.executable))
    local_model_path = os.path.join(os.path.dirname(sys.executable), "models")
    if not os.path.exists(local_model_path):
        local_model_path = os.path.join(base_path, "models")
else:
    local_model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

if os.path.exists(local_model_path):
    os.environ["U2NET_HOME"] = local_model_path


class AIBackgroundRemoverApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AI 智能抠图工具 Pro (极速稳定版 v3.1)")
        self.geometry("1200x750")
        ctk.set_appearance_mode("Dark")

        # --- 变量 ---
        self.original_image = None
        self.processed_image = None
        self.current_model = "u2net"
        self.sessions = {}
        self.session_lock = threading.Lock()

        # --- UI ---
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._init_sidebar()
        self._init_main_area()

        # --- 启动后台加载 ---
        self.status_label.configure(text="正在初始化 AI 引擎 (首次需几秒)...")
        # 延迟执行，让界面先显示出来
        self.after(100, lambda: threading.Thread(target=self._preload_libraries, daemon=True).start())

    def _preload_libraries(self):
        """后台静默加载库，预热缓存"""
        try:
            # 这里单纯为了触发 import，把重型库加载进内存
            import rembg
            import onnxruntime
            print("后台库加载完成")
            # 预加载默认模型的 session (可选，会加快第一次点击速度)
            self._get_session("u2net")
        except Exception as e:
            print(f"预加载警告: {e}")

    def _init_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(self.sidebar_frame, text="AI Remover Pro", font=ctk.CTkFont(size=22, weight="bold")).pack(
            pady=(30, 20))

        ctk.CTkLabel(self.sidebar_frame, text="第一步: 导入", text_color="gray").pack(anchor="w", padx=20, pady=(10, 0))
        self.btn_upload = ctk.CTkButton(self.sidebar_frame, text="📂 打开图片", height=40, command=self.load_image)
        self.btn_upload.pack(padx=20, pady=10)

        ctk.CTkLabel(self.sidebar_frame, text="第二步: 算法设置", text_color="gray").pack(anchor="w", padx=20,
                                                                                          pady=(20, 0))

        self.model_var = ctk.StringVar(value="u2net (标准)")
        self.model_menu = ctk.CTkOptionMenu(self.sidebar_frame,
                                            values=["u2net (标准)", "isnet-general-use (高精度)",
                                                    "isnet-anime (动漫专用)"],
                                            command=self.change_model,
                                            variable=self.model_var)
        self.model_menu.pack(padx=20, pady=10)

        self.use_alpha_matting = ctk.BooleanVar(value=False)
        self.switch_matting = ctk.CTkSwitch(self.sidebar_frame, text="边缘精修 (Alpha Matting)",
                                            variable=self.use_alpha_matting,
                                            onvalue=True, offvalue=False)
        self.switch_matting.pack(padx=20, pady=10)

        self.tip_label = ctk.CTkLabel(self.sidebar_frame, text="💡 提示: models目录需包含\nonnx文件以离线运行",
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

        self.label_orig = ctk.CTkLabel(self.main_frame, text="原始图片", width=400, height=500,
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
            # 后台切换，防止卡顿
            threading.Thread(target=self._get_session, args=(new_model,), daemon=True).start()

    def _get_session(self, model_name):
        """获取 Session (线程安全)"""
        with self.session_lock:
            # 【修复1】无条件导入，解决 UnboundLocalError
            from rembg import new_session

            if model_name not in self.sessions:
                try:
                    # 使用 self.after 安全地更新 UI 文本（虽然这里在后台线程，但 CTk 的 configure 有时会警告）
                    self.status_label.configure(text=f"加载模型 {model_name}...")

                    providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
                    session = new_session(model_name, providers=providers)
                    self.sessions[model_name] = session

                    self.status_label.configure(text=f"模型 {model_name} 就绪")
                except Exception as e:
                    print(f"Model Init Error: {e}")
                    self.status_label.configure(text="加载失败: 请检查文件")
                    return None
            return self.sessions[model_name]

    def load_image(self):
        file_path = filedialog.askopenfilename(filetypes=[("Images", "*.jpg;*.png;*.webp;*.jpeg")])
        if file_path:
            self.original_image = Image.open(file_path)
            self._display_image(self.original_image, self.label_orig)
            self.label_result.configure(image=None, text="等待处理...")
            self.processed_image = None
            self.btn_process.configure(state="normal")
            self.btn_save.configure(state="disabled")

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
            # 【修复1】无条件导入
            from rembg import remove

            session = self._get_session(model_name)
            if not session: raise Exception("模型加载失败")

            res = remove(self.original_image, session=session, alpha_matting=alpha_matting,
                         alpha_matting_foreground_threshold=240, alpha_matting_background_threshold=10)
            self.processed_image = res
            self.after(0, lambda: self._success_callback(time.time() - start_t))
        except Exception as e:
            # 【修复2】先将错误转为字符串，防止变量作用域丢失
            err_msg = str(e)
            self.after(0, lambda: self._error_callback(err_msg))

    def _success_callback(self, elapsed):
        self._display_image(self.processed_image, self.label_result)
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

    def _display_image(self, img, label):
        target_w, target_h = label.winfo_width(), label.winfo_height()
        if target_w < 50: target_w, target_h = 400, 500
        img_copy = img.copy()
        img_copy.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=img_copy, dark_image=img_copy, size=img_copy.size)
        label.configure(image=ctk_img, text="")
        label._current_image = ctk_img

    def save_image(self):
        if self.processed_image:
            path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")])
            if path: self.processed_image.save(path)


if __name__ == "__main__":
    app = AIBackgroundRemoverApp()
    app.mainloop()
