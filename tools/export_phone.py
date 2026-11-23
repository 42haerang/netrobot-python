"""Convert a YOLOv8 checkpoint to a small, fixed-input ONNX model for Android."""
import argparse
import json
import os
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'models/.yolo'))
os.environ.setdefault('YOLO_AUTOINSTALL','false')


def export(weights,trained=True):
    from ultralytics import YOLO
    model=YOLO(str(weights))
    output=model.export(format='onnx',imgsz=320,batch=1,opset=12,simplify=False,dynamic=False,nms=False,device='cpu')
    folder=ROOT/'phone/models'
    folder.mkdir(exist_ok=True)
    shutil.copy2(output,folder/'net.onnx')
    info={'size':320,'names':[model.names[i] for i in range(len(model.names))],'trained_on_net':trained,
          'source_checkpoint':str(Path(weights).name),'framework':'Ultralytics YOLOv8, OpenCV DNN, ONNX opset 12'}
    (folder/'model.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXPORTED',folder/'net.onnx',flush=True)
    return folder/'net.onnx'


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('weights')
    parser.add_argument('--demo',action='store_true')
    args=parser.parse_args()
    export(args.weights,not args.demo)
