from libs.PipeLine import PipeLine
from libs.AIBase import AIBase
from libs.AI2D import Ai2d
from libs.Utils import *
import os, sys, ujson, gc, math
from media.media import *
import nncase_runtime as nn
import ulab.numpy as np
import image
import aidemo
from machine import UART
from machine import FPIOA
from machine import PWM
import time


OBSTACLE_CLASSES = ["person", "bicycle", "car", "motorcycle", "bus", "train", "truck"]
# 危险等级阈值（检测框面积占比，越大越近）
DANGER_FAR = 0.05    # 远距离：缓慢提醒
DANGER_MID = 0.15    # 中距离：中等提醒
DANGER_NEAR = 0.3    # 近距离：紧急提醒

# 全局初始化蜂鸣器
beep_io = FPIOA()
beep_io.set_function(43, FPIOA.PWM1)
beep_pwm = PWM(1)
beep_pwm.freq(4000)
beep_pwm.duty_u16(0)

last_beep_time = 0

# Custom YOLOv8 object detection class
class ObjectDetectionApp(AIBase):
    def __init__(self, kmodel_path, labels, model_input_size, max_boxes_num, confidence_threshold=0.5, nms_threshold=0.2, rgb888p_size=[224,224], display_size=[1920,1080], debug_mode=0):
        super().__init__(kmodel_path, model_input_size, rgb888p_size, debug_mode)
        self.kmodel_path = kmodel_path
        self.labels = labels
        self.model_input_size = model_input_size
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.max_boxes_num = max_boxes_num

        self.rgb888p_size = [ALIGN_UP(rgb888p_size[0], 16), rgb888p_size[1]]
        self.display_size = [ALIGN_UP(display_size[0], 16), display_size[1]]
        self.debug_mode = debug_mode
        self.color_four = get_colors(len(self.labels))
        self.x_factor = float(self.rgb888p_size[0]) / self.model_input_size[0]
        self.y_factor = float(self.rgb888p_size[1]) / self.model_input_size[1]

        self.ai2d = Ai2d(debug_mode)
        self.ai2d.set_ai2d_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT, np.uint8, np.uint8)

        # UART（可选，用于数据传输）
        self.fpioa = FPIOA()
        self.fpioa.set_function(3, self.fpioa.UART1_TXD, ie=1, oe=1)
        self.fpioa.set_function(4, self.fpioa.UART1_RXD, ie=1, oe=1)
        self.uart = UART(UART.UART1, baudrate=115200, bits=UART.EIGHTBITS, parity=UART.PARITY_NONE, stop=UART.STOPBITS_ONE)

    def config_preprocess(self, input_image_size=None):
        with ScopedTiming("set preprocess config", self.debug_mode > 0):
            ai2d_input_size = input_image_size if input_image_size else self.rgb888p_size
            top, bottom, left, right, self.scale = letterbox_pad_param(self.rgb888p_size, self.model_input_size)
            self.ai2d.pad([0,0,0,0,top,bottom,left,right], 0, [128,128,128])
            self.ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
            self.ai2d.build([1,3,ai2d_input_size[1],ai2d_input_size[0]], [1,3,self.model_input_size[1],self.model_input_size[0]])

    def preprocess(self, input_np):
        return [nn.from_numpy(input_np)]

    def postprocess(self, results):
        new_result = results[0][0].transpose()
        det_res = aidemo.yolov8_det_postprocess(
            new_result.copy(),
            [self.rgb888p_size[1], self.rgb888p_size[0]],
            [self.model_input_size[1], self.model_input_size[0]],
            [self.display_size[1], self.display_size[0]],
            len(self.labels),
            self.confidence_threshold,
            self.nms_threshold,
            self.max_boxes_num
        )
        return det_res

    def draw_result(self, pl, dets):
        global beep_pwm, last_beep_time

        max_danger = 0  # 记录最高危险等级
        pl.osd_img.clear()

        if dets and len(dets[0]) > 0:
            for i in range(len(dets[0])):
                label_idx = dets[1][i]
                label_name = self.labels[label_idx]

                # 只处理避障关键类别
                if label_name not in OBSTACLE_CLASSES:
                    continue

                x, y, w, h = map(lambda x: int(round(x, 0)), dets[0][i])
                conf = round(dets[2][i], 2)

                # 计算检测框面积占比（粗略判断距离）
                box_area = w * h
                screen_area = self.display_size[0] * self.display_size[1]
                area_ratio = box_area / screen_area

                # 确定危险等级
                danger_level = 0
                if area_ratio > DANGER_NEAR:
                    danger_level = 3  # 近距离：紧急
                elif area_ratio > DANGER_MID:
                    danger_level = 2  # 中距离：中等
                elif area_ratio > DANGER_FAR:
                    danger_level = 1  # 远距离：缓慢

                max_danger = max(max_danger, danger_level)

                # 绘制检测框和信息
                color = (255,0,0) if danger_level >=2 else (0,255,0) if danger_level ==1 else (255,255,0)
                pl.osd_img.draw_rectangle(x, y, w, h, color=color, thickness=4)
                pl.osd_img.draw_string_advanced(x, y-50, 32, f"{label_name} {conf} Lv{danger_level}", color=color)

        # 根据最高危险等级控制蜂鸣器
        now = time.ticks_ms()
        if max_danger == 0:
            # 安全：不响
            beep_pwm.duty_u16(0)
        elif max_danger == 1 and now - last_beep_time > 1500:
            # 远距离：滴一声，间隔1.5秒
            beep_pwm.duty_u16(32768)
            time.sleep_ms(80)
            beep_pwm.duty_u16(0)
            last_beep_time = now
        elif max_danger == 2 and now - last_beep_time > 800:
            # 中距离：滴一声，间隔0.8秒
            beep_pwm.duty_u16(32768)
            time.sleep_ms(100)
            beep_pwm.duty_u16(0)
            last_beep_time = now
        elif max_danger == 3 and now - last_beep_time > 300:
            # 近距离：急促滴滴滴
            beep_pwm.duty_u16(32768)
            time.sleep_ms(150)
            beep_pwm.duty_u16(0)
            last_beep_time = now

if __name__ == "__main__":
    display_mode = "lcd"
    rgb888p_size = [224, 224]
    kmodel_path = "/sdcard/examples/kmodel/yolov8n_224.kmodel"

    # COCO数据集标签
    labels = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
              "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
              "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
              "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
              "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
              "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
              "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
              "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
              "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
              "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"]

    # 较高置信度，减少误报
    confidence_threshold = 0.6
    nms_threshold = 0.4
    max_boxes_num = 10  # 减少同时处理的目标数，提高效率

    pl = PipeLine(rgb888p_size=rgb888p_size, display_mode=display_mode)
    pl.create()
    display_size = pl.get_display_size()

    ob_det = ObjectDetectionApp(
        kmodel_path,
        labels=labels,
        model_input_size=[224,224],
        max_boxes_num=max_boxes_num,
        confidence_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
        rgb888p_size=rgb888p_size,
        display_size=display_size,
        debug_mode=0
    )
    ob_det.config_preprocess()

    while True:
        with ScopedTiming("total", 1):
            img = pl.get_frame()
            res = ob_det.run(img)
            ob_det.draw_result(pl, res)
            pl.show_image()
            gc.collect()
