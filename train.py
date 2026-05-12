from ultralytics import YOLO
import os

# 彻底关闭GitHub下载报错，国内环境专用
os.environ["ULTRALYTICS_NO_DOWNLOAD"] = "true"
os.environ["AMP_DISABLE"] = "1"

# ===================== 核心：盲道单类别 最优训练代码 =====================
if __name__ == '__main__':
    # 加载轻量化模型，适配K230芯片
    model = YOLO("yolov8n.pt")

    # 🔥 全最优参数（盲道识别专用）
    model.train(
        # 基础配置
        data="data.yaml",  # 你的配置文件（必须nc=1，仅盲道）
        imgsz=320,  # 最适合盲道纹理的尺寸
        device=0,  # 使用RTX5060显卡
        epochs=150,  # 训练轮数
        patience=50,  # 延长耐心值，更好学习纹理
        batch=8,  # 笔记本显卡最优批次
        workers=2,  # Windows稳定线程（最佳值）

        # 单类别盲道 核心优化（精度关键）
        single_cls=True,  # 声明单类别任务，大幅提升精度
        augment=False,  # 关闭冗余增强，保护盲道条纹不被破坏
        cache="disk",  # 加速数据读取

        # 优化训练策略
        cos_lr=True,  # 余弦学习率，收敛更好
        lr0=0.01,  # 初始学习率（最优）
        lrf=0.01,  # 末学习率
        warmup_epochs=3,  # 热身轮数

        # 保存配置
        project="blind_cane_train",
        name="tactile_best",  # 保存文件夹
        save=True,
        save_period=10,
        val=True,
        plots=True
    )

    # ===================== 自动导出 K230 专用 ONNX 模型 =====================
    print("\n===== 训练完成，开始导出最优模型 =====")
    model.export(
        format="onnx",
        imgsz=320,
        simplify=True,  # 简化模型（K230必须）
        opset=11,  # K230兼容版本
        dynamic=False,  # 固定尺寸（必须关闭）
        nms=False  # 关闭内置NMS（必须）
    )

    print("\n===== 全部完成！模型已导出，直接用于智能盲杖 =====")