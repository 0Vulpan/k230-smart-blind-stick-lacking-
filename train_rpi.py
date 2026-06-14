import os
import sys
import math
import time
from datetime import datetime

import torch
import torch.nn as nn
from ultralytics import YOLO
from ultralytics.utils.torch_utils import select_device

class ECA(nn.Module):
    def __init__(self, channels=None, k_size=None):
        super().__init__()
        if k_size is None and channels is not None:
            k_size = int(abs((math.log(channels, 2) + 1) / 2))
            k_size = k_size if k_size % 2 else k_size + 1
        elif k_size is None:
            k_size = 7
        self.conv = nn.Conv1d(1, 1, kernel_size=k_size, padding=(k_size - 1) // 2, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        b, c, h, w = x.shape
        y = torch.mean(x, dim=(2, 3), keepdim=True)
        y = y.squeeze(-1).permute(0, 2, 1)
        y = self.conv(y)
        y = self.sigmoid(y)
        y = y.permute(0, 2, 1).unsqueeze(-1)
        return x * y

class C2fWithECA(nn.Module):
    def __init__(self, c2f_module):
        super().__init__()
        self.c2f = c2f_module
        out_ch = self.c2f.cv2.conv.out_channels
        self.eca = ECA(channels=out_ch)

    def forward(self, x):
        x = self.c2f(x)
        return self.eca(x)

def inject_eca_into_yolo(model):
    eca_count = 0
    replace_queue = []
    for full_name, module in model.model.named_modules():
        if type(module).__name__ == "C2f":
            replace_queue.append((full_name, module))
    for name, c2f_mod in replace_queue:
        name_parts = name.split(".")
        parent_module = model.model
        for part in name_parts[:-1]:
            parent_module = getattr(parent_module, part)
        new_mod = C2fWithECA(c2f_mod)
        setattr(parent_module, name_parts[-1], new_mod)
        eca_count += 1
    print("SUCCESS: ECA attention inserted into %d C2f modules" % eca_count)
    return model

def export_to_onnx(model, save_dir, imgsz=640):
    best_pt_path = os.path.join(save_dir, "weights", "best.pt")
    if not os.path.exists(best_pt_path):
        print("WARNING: Best weights not found:", best_pt_path)
        return None
    
    print("Exporting ONNX model...")
    export_model = YOLO(best_pt_path)
    
    try:
        export_success = export_model.export(
            format="onnx",
            imgsz=imgsz,
            opset=17,
            simplify=True,
            dynamic=False,
            device="cpu"
        )
        
        if export_success:
            onnx_path = os.path.splitext(best_pt_path)[0] + ".onnx"
            print("SUCCESS: ONNX model exported to:", onnx_path)
            return onnx_path
        else:
            print("ERROR: ONNX export failed")
            return None
    except Exception as e:
        print("ERROR during ONNX export:", str(e))
        import traceback
        traceback.print_exc()
        return None

def main():
    start_time = time.time()
    print("=" * 60)
    print("YOLOv8n + ECA Training Script")
    print("Date:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)
    
    device = select_device(0)
    print("Using device:", device)

    print("\nInitializing YOLOv8n model...")
    model = YOLO("yolov8n.yaml")
    print("SUCCESS: Model structure initialized")

    print("\nLoading pretrained weights yolov8n.pt...")
    model.load("yolov8n.pt")
    print("SUCCESS: Pretrained weights loaded")

    print("\nInjecting ECA attention modules...")
    model = inject_eca_into_yolo(model)
    print("SUCCESS: ECA injection completed")

    print("\n" + "=" * 60)
    print("Starting training...")
    print("=" * 60)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = "yolov8n-eca_%s" % timestamp
    
    print("\nRun name:", run_name)
    print("This training will be saved to: runs/train/%s" % run_name)
    
    results = model.train(
        data="data.yaml",
        epochs=400,
        batch=8,
        imgsz=640,
        device=device,
        workers=4,
        project="runs/train",
        name=run_name,
        pretrained=True,
        patience=30,
        save_period=10,
        amp=True,
        exist_ok=False,
        
        lr0=0.0005,
        lrf=0.005,
        momentum=0.95,
        weight_decay=0.0001,
        warmup_epochs=10,
        
        hsv_h=0.02,
        hsv_s=0.3,
        hsv_v=0.25,
        degrees=3.0,
        fliplr=0.5,
        scale=0.2,
        perspective=0.001,
        flipud=0.0,
        mosaic=0.9,
        mixup=0.0,
        copy_paste=0.0,
        close_mosaic=5,
        
        cos_lr=True,
        label_smoothing=0.02,
        overlap_mask=False,
        val=True,
        save_json=True,
        plots=True,
        
        optimizer="AdamW",
        box=6.0,
        cls=1.0,
        dfl=1.5,
    )

    training_time = time.time() - start_time
    print("\n" + "=" * 60)
    print("Training completed!")
    print("Total training time: %.2f hours" % (training_time / 3600))
    print("Best weights:", "%s/weights/best.pt" % results.save_dir)
    print("=" * 60)

    onnx_path = export_to_onnx(model, results.save_dir)
    
    total_time = time.time() - start_time
    print("\n" + "=" * 60)
    print("Total time: %.2f hours" % (total_time / 3600))
    print("=" * 60)

    return results, onnx_path

if __name__ == "__main__":
    main()
